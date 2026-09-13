# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L)
# SPDX-License-Identifier: AGPL-3.0-only
# "LumenPDF" and "LumenPDF Studio" are trademarks of Lumen Solutions. See TRADEMARKS.md.
"""Wire BrandPDF into ERPNext's native PDF flows (the BrandPDF Mapping toggles).

- replace_print_pdf: overrides `frappe.utils.print_format.download_pdf` — the endpoint behind the
  Print view's PDF button, the grid's PDF shortcut, and /api/method/...download_pdf links. When an
  enabled mapping with the toggle exists for the doctype, the branded PDF is returned instead of
  the native print format; on ANY failure it falls back to the native implementation so printing
  never breaks.
- auto_attach: after Submit of a mapped doctype, renders the branded PDF in the background and
  attaches it to the document (so it is ready to email/share).

The render here is synchronous inside the web request (like print_designer) — the background
job queue and its Redis lock are for the interactive builder/preview paths; a rare concurrent
Chromium with a worker render is acceptable.
"""
import re

import frappe


def _mapping(doctype, flag, company=None):
    """Template name from the highest-priority enabled mapping with `flag` on. A mapping scoped
    to the doc's company wins over the global (blank-company) one; other companies' rows never
    apply. Returns None when unmapped."""
    if not doctype:
        return None
    try:
        if not frappe.db.exists("DocType", "BrandPDF Mapping"):
            return None
        # Select in PYTHON: legacy rows have company = NULL (SQL IN-filters never match NULL),
        # and another company's mapping must never leak in as a fallback.
        try:
            rows = frappe.get_all("BrandPDF Mapping", filters={"target_doctype": doctype, "enabled": 1, flag: 1},
                                  fields=["template", "company"], order_by="priority asc, creation asc")
        except Exception:
            rows = [{"template": t, "company": None} for t in frappe.get_all(
                "BrandPDF Mapping", filters={"target_doctype": doctype, "enabled": 1, flag: 1},
                pluck="template", order_by="priority asc, creation asc")]
        if company:
            for r in rows:
                if (r.get("company") or "") == company:
                    return r["template"]
        for r in rows:
            if not r.get("company"):
                return r["template"]
        return None
    except Exception:
        # Fail safe to 'unmapped' (native PDF keeps working) but leave a trace — a silent
        # swallow here would make branded PDFs vanish with nothing to diagnose.
        try:
            frappe.log_error(message=frappe.get_traceback(), title="BrandPDF mapping lookup failed")
        except Exception:
            pass
        return None


@frappe.whitelist()
def download_pdf(doctype, name, format=None, doc=None, *args, **kwargs):
    """Drop-in override of frappe.utils.print_format.download_pdf (same signature, tolerant tail)."""
    company = None
    try:
        df = frappe.get_meta(doctype).get_field("company")
        if df and getattr(df, "fieldtype", "") == "Link" and getattr(df, "options", "") == "Company":
            company = frappe.db.get_value(doctype, name, "company")
    except Exception:
        company = None
    template = _mapping(doctype, "replace_print_pdf", company)
    if template:
        # Same Redis NX lock as the background jobs: at most ONE Chromium render at a time.
        # If the renderer is busy, we don't queue the web request — we fall back to the native
        # PDF instead, so the endpoint can't be used to stack up concurrent Chromiums (DoS).
        from brandpdf.pdf_job import _acquire, _release
        lock = "brandpdf_render_lock_" + (getattr(frappe.local, "site", None) or "site")
        if _acquire(lock, "sync-print"):
            try:
                d = frappe.get_doc(doctype, name)
                d.check_permission("read")
                if not frappe.has_permission(doctype, "print", doc=d):
                    raise frappe.PermissionError
                d.apply_fieldlevel_read_permissions()
                from brandpdf.compose import compose_pdf
                pdf = compose_pdf(d, template=template)
                if pdf:
                    safe = re.sub(r"[^\w\-.]", "-", str(name))
                    # Frappe v15 file-response pattern: the framework reads these three
                    # frappe.local.response fields after the handler returns.
                    frappe.local.response.filename = f"{safe}.pdf"
                    frappe.local.response.filecontent = pdf
                    frappe.local.response.type = "pdf"
                    return
            except frappe.PermissionError:
                raise  # never fall back around a permission denial
            except Exception:
                frappe.log_error(message=frappe.get_traceback(), title="BrandPDF replace_print_pdf fell back")
            finally:
                _release(lock)
    from frappe.utils.print_format import download_pdf as native
    return native(doctype, name, format, doc, *args, **kwargs)


def auto_attach_on_submit(doc, method=None):
    """doc_events['*'].on_submit: attach the branded PDF after submit of a mapped doctype."""
    try:
        template = _mapping(doc.doctype, "auto_attach", doc.get("company"))
        if not template:
            return
        frappe.enqueue(
            "brandpdf.overrides._attach_pdf", queue="long", timeout=180,
            doctype=doc.doctype, docname=doc.name, template=template,
            enqueue_after_commit=True,
        )
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="BrandPDF auto-attach enqueue failed")


def _attach_pdf(doctype, docname, template=None):
    try:
        doc = frappe.get_doc(doctype, docname)
        from brandpdf.compose import compose_pdf
        pdf = compose_pdf(doc, template=template)
        if not pdf:
            return  # compose already logged; a background attach has no fallback — just skip
        # NOTE: name must NOT end in '-brandpdf.pdf' — cleanup_expired_files purges that pattern.
        f = frappe.get_doc({
            "doctype": "File", "file_name": f"{docname}-branded.pdf", "is_private": 1,
            "content": pdf, "attached_to_doctype": doctype, "attached_to_name": docname,
        })
        f.flags.ignore_permissions = True
        f.insert()
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="BrandPDF auto-attach failed")
