"""Background render job (runs on the 'long' queue worker) + daily cleanup.

Hardening from code review:
- H1: a Redis NX lock serializes renders to ONE concurrent Chromium even if multiple long
  workers exist (degrades gracefully to single-worker serialization if the lock backend errs).
- M1: the worker's session user is restored in `finally` (RQ workers are long-lived).
- M3: permission failures are reported distinctly; the real traceback is logged.
- L2: field-level read permissions are applied so permlevel-restricted values never reach the PDF.
"""
import frappe

from brandpdf.api import set_state
from brandpdf.config import conf
from brandpdf.render.base import default_options, get_renderer
from brandpdf.render_html import render_html


def generate(job_token, doctype, docname, user, template=None, _retry=0):
    job_id = job_token  # frappe.enqueue reserves 'job_id', so callers pass ours as 'job_token'
    lock = "brandpdf_render_lock_" + (frappe.local.site or "site")
    if not _acquire(lock, job_id):
        # Another render holds the lock. Re-enqueue; the single long worker runs it next.
        if _retry < 60:
            frappe.enqueue(
                "brandpdf.pdf_job.generate", queue="long",
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
            doc.apply_fieldlevel_read_permissions()
        except frappe.PermissionError:
            set_state(job_id, {"status": "error", "message": "You are not permitted to print this document."}, user)
            return

        from brandpdf.compose import compose_pdf
        pdf_bytes = compose_pdf(doc, template=template)  # chosen format (or default) + running header/footer
        file_url = _save_private_file(doc, pdf_bytes, docname)
        set_state(job_id, {"status": "done", "file_url": file_url}, user)
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="BrandPDF render failed")
        set_state(job_id, {"status": "error", "message": "Render failed — see Error Log."}, user)
    finally:
        frappe.set_user(prev_user)
        _release(lock)


# --- concurrency lock (H1) -------------------------------------------------

def _acquire(lock, job_id):
    try:
        # raw redis SET NX EX; returns True if acquired, None/False if held.
        return bool(frappe.cache().set(lock, job_id, nx=True, ex=240))
    except Exception:
        # Backend doesn't support NX set -> degrade to relying on a single long worker.
        return True


def _release(lock):
    try:
        frappe.cache().delete(lock)
    except Exception:
        pass


# --- file output -----------------------------------------------------------

def _save_private_file(doc, pdf_bytes, docname):
    f = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": f"{docname}-brandpdf.pdf",
            "is_private": 1,
            "content": pdf_bytes,
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
        }
    )
    f.flags.ignore_permissions = True
    f.insert()
    return f.file_url


def cleanup_expired_files():
    """Daily: remove BrandPDF private files older than 1 day (regenerated on demand)."""
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-1)
    names = frappe.get_all(
        "File",
        filters={"is_private": 1, "file_name": ("like", "%-brandpdf.pdf"), "creation": ("<", cutoff)},
        pluck="name",
    )
    for n in names:
        try:
            frappe.delete_doc("File", n, ignore_permissions=True, delete_permanently=True)
        except Exception:
            frappe.log_error(title="BrandPDF cleanup failed")
