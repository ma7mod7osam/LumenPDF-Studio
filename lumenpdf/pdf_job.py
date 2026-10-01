# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Background render job (runs on the 'long' queue worker) + daily cleanup.

Hardening from code review:
- H1: a Redis NX lock serializes renders to ONE concurrent Chromium even if multiple long
  workers exist (degrades gracefully to single-worker serialization if the lock backend errs).
- M1: the worker's session user is restored in `finally` (RQ workers are long-lived).
- M3: permission failures are reported distinctly; the real traceback is logged.
- L2: field-level read permissions are applied so permlevel-restricted values never reach the PDF.
"""
import re

import frappe

from lumenpdf.api import set_state
from lumenpdf.config import conf
from lumenpdf.render.base import default_options, get_renderer
from lumenpdf.render_html import render_html


def generate(job_token, doctype, docname, user, template=None, _retry=0):
    job_id = job_token  # frappe.enqueue reserves 'job_id', so callers pass ours as 'job_token'
    lock = _acquire_slot(job_id)
    if not lock:
        # Another render holds the lock. Re-enqueue; the single long worker runs it next.
        if _retry < 60:
            frappe.enqueue(
                "lumenpdf.pdf_job.generate", queue="long",
                timeout=(conf("render_timeout") or 120) + 30,
                job_token=job_id, doctype=doctype, docname=docname, user=user, template=template, _retry=_retry + 1,
            )
        else:
            set_state(job_id, {"status": "error", "message": "Renderer busy; please retry."}, user)
        return

    prev_user = frappe.session.user
    try:
        frappe.set_user(user)
        doc = frappe.get_doc(doctype, docname)
        try:
            doc.check_permission("read")
            if not frappe.has_permission(doctype, "print", doc=doc):
                raise frappe.PermissionError  # enforce 'print' at the actual render site too
            doc.apply_fieldlevel_read_permissions()
        except frappe.PermissionError:
            set_state(job_id, {"status": "error", "message": "You are not permitted to print this document."}, user)
            return

        from lumenpdf.compose import compose_pdf
        pdf_bytes = compose_pdf(doc, template=template)  # chosen format (or default) + running header/footer
        saved = _save_private_file(doc, pdf_bytes, docname, template)
        set_state(job_id, dict(saved, status="done"), user)
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="LumenPDF render failed")
        set_state(job_id, {"status": "error", "message": "Render failed — see Error Log."}, user)
    finally:
        frappe.set_user(prev_user)
        _release(lock)


def generate_preview(job_token, definition, doctype, docname, user, _retry=0):
    """Render an UNSAVED builder definition to a PDF (the 'Preview PDF' button). Same lock/perm/
    private-file path as generate(), but composes the passed definition instead of a saved one."""
    job_id = job_token
    lock = "lumenpdf_render_lock_" + (frappe.local.site or "site")
    if not _acquire(lock, job_id):
        if _retry < 60:
            frappe.enqueue(
                "lumenpdf.pdf_job.generate_preview", queue="long",
                timeout=(conf("render_timeout") or 120) + 30,
                job_token=job_id, definition=definition, doctype=doctype, docname=docname, user=user, _retry=_retry + 1,
            )
        else:
            set_state(job_id, {"status": "error", "message": "Renderer busy; please retry."}, user)
        return

    prev_user = frappe.session.user
    try:
        frappe.set_user(user)
        if "System Manager" not in frappe.get_roles():
            set_state(job_id, {"status": "error", "message": "Not permitted."}, user)
            return
        doc = frappe.get_doc(doctype, docname)
        try:
            doc.check_permission("read")
            if not frappe.has_permission(doctype, "print", doc=doc):
                raise frappe.PermissionError
            doc.apply_fieldlevel_read_permissions()
        except frappe.PermissionError:
            set_state(job_id, {"status": "error", "message": "You are not permitted to print this document."}, user)
            return

        import json as _json
        d = _json.loads(definition) if isinstance(definition, str) else definition
        from lumenpdf import compose, blocks as B, assets
        from lumenpdf.render.base import get_renderer, default_options
        renderer = get_renderer()
        pdf = None
        if isinstance(d, dict) and d.get("layout") == "absolute":
            pdf = compose._compose(doc, d, renderer)
        if not pdf:
            html = B.render_definition(doc, d, "")
            br = (d.get("branding") or {}) if isinstance(d, dict) else {}
            allowed = {src for src in (br.get("header_image"), br.get("footer_image")) if src} | B.collect_image_srcs(d)
            allowed |= B.collect_doc_image_srcs(doc, d)  # item photos + Data Table image lines
            html = assets.neutralize_remote(assets.inline_images(html, allowed=allowed))
            pdf = renderer.render(html, default_options())
        saved = _save_private_file(doc, pdf, docname + "-preview")
        set_state(job_id, dict(saved, status="done"), user)
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="LumenPDF preview failed")
        set_state(job_id, {"status": "error", "message": "Preview failed — see Error Log."}, user)
    finally:
        frappe.set_user(prev_user)
        _release(lock)


# --- concurrency lock (H1) -------------------------------------------------

def _acquire_slot(job_id):
    """Take one of a few renderer slots, and say which. Chromium is heavy, so the count stays
    small and bounded: that is what keeps a burst of print clicks from stacking up browsers.
    One slot was too few, two people printing at the same time meant one of them waiting."""
    site = frappe.local.site or "site"
    slots = conf("render_slots")
    try:
        slots = max(1, min(8, int(slots)))
    except (TypeError, ValueError):
        slots = 2
    for i in range(slots):
        lock = f"lumenpdf_render_lock_{site}_{i}"
        if _acquire(lock, job_id):
            return lock
    return None


def _acquire(lock, job_id):
    try:
        # raw redis SET NX EX; returns True if acquired, None/False if held.
        # A real lock needs an atomic SET NX EX, which set_value() does not offer. The key is made
        # site-scoped with make_key(), so locks never collide across sites on a shared bench.
        return bool(frappe.cache().set(frappe.cache().make_key(lock), job_id, nx=True, ex=240))  # nosemgrep
    except Exception:
        # Backend doesn't support NX set -> degrade to relying on a single long worker.
        return True


def _release(lock):
    try:
        frappe.cache().delete_value(lock)  # applies the same site-scoped make_key()
    except Exception:
        pass


# --- file output -----------------------------------------------------------

def file_suffix(template=None):
    """The tail of a rendered file name. It carries the format, so a cached file is only reused
    for the format it was printed with."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(template or "default")).strip("-").lower()[:40]
    return f"-{slug}-lumenpdf.pdf"


def _save_private_file(doc, pdf_bytes, docname, template=None):
    """Returns what a caller needs to hand the file on: the url to show it, and the File record
    itself, because the email composer attaches by File name, not by url."""
    f = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": f"{docname}{file_suffix(template)}",
            "is_private": 1,
            "content": pdf_bytes,
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
        }
    )
    f.flags.ignore_permissions = True
    f.insert()
    return {"file_url": f.file_url, "file_name": f.file_name, "file_id": f.name}


def cleanup_expired_files():
    """Daily: remove LumenPDF private files older than 1 day (regenerated on demand)."""
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-1)
    names = frappe.get_all(
        "File",
        filters={"is_private": 1, "file_name": ("like", "%-lumenpdf.pdf"), "creation": ("<", cutoff)},
        pluck="name",
    )
    for n in names:
        try:
            frappe.delete_doc("File", n, ignore_permissions=True, delete_permanently=True)
        except Exception:
            frappe.log_error(title="LumenPDF cleanup failed")
