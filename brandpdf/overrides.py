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


def _mapping(doctype, flag):
    """Template name from the highest-priority enabled mapping with `flag` on, else None."""
    if not doctype:
        return None
    try:
        if not frappe.db.exists("DocType", "BrandPDF Mapping"):
            return None
        rows = frappe.get_all(
            "BrandPDF Mapping",
            filters={"target_doctype": doctype, "enabled": 1, flag: 1},
            fields=["template"], order_by="priority asc", limit=1,
        )
        return rows[0]["template"] if rows else None
    except Exception:
        return None  # mapping table missing a column (old install) etc. -> behave as unmapped


@frappe.whitelist()
def download_pdf(doctype, name, format=None, doc=None, *args, **kwargs):
    """Drop-in override of frappe.utils.print_format.download_pdf (same signature, tolerant tail)."""
    template = _mapping(doctype, "replace_print_pdf")
    if template:
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
                frappe.local.response.filename = f"{safe}.pdf"
                frappe.local.response.filecontent = pdf
                frappe.local.response.type = "pdf"
                return
        except frappe.PermissionError:
            raise  # never fall back around a permission denial
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="BrandPDF replace_print_pdf fell back")
    from frappe.utils.print_format import download_pdf as native
    return native(doctype, name, format, doc, *args, **kwargs)


def auto_attach_on_submit(doc, method=None):
    """doc_events['*'].on_submit: attach the branded PDF after submit of a mapped doctype."""
    try:
        template = _mapping(doc.doctype, "auto_attach")
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
            return
        # NOTE: name must NOT end in '-brandpdf.pdf' — cleanup_expired_files purges that pattern.
        f = frappe.get_doc({
            "doctype": "File", "file_name": f"{docname}-branded.pdf", "is_private": 1,
            "content": pdf, "attached_to_doctype": doctype, "attached_to_name": docname,
        })
        f.flags.ignore_permissions = True
        f.insert()
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="BrandPDF auto-attach failed")
