"""Background render job (runs on the 'long' queue worker) + daily cleanup.

Re-checks permission as the requesting user (so branding/permlevel resolve correctly),
renders the HTML, drives the engine, saves a PRIVATE File attached to the doc, and
publishes the result to the cache for the polling client.
"""
import frappe

from brandpdf.render.base import default_options, get_renderer
from brandpdf.render_html import render_html

_FILE_TAG = "BrandPDF"


def generate(job_id, doctype, docname, template, user):
    key = f"brandpdf:job:{job_id}"
    try:
        frappe.set_user(user)
        doc = frappe.get_doc(doctype, docname)
        doc.check_permission("read")

        html = render_html(doc, template)
        pdf_bytes = get_renderer().render(html, default_options())
        file_url = _save_private_file(doc, pdf_bytes, docname)

        frappe.cache().set_value(key, {"status": "done", "file_url": file_url}, expires_in_sec=900)
    except Exception:
        frappe.log_error(title="BrandPDF render failed")
        frappe.cache().set_value(
            key, {"status": "error", "message": "Render failed — see Error Log."}, expires_in_sec=900
        )


def _save_private_file(doc, pdf_bytes, docname):
    f = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": f"{docname}-brandpdf.pdf",
            "is_private": 1,
            "content": pdf_bytes,
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "attached_to_field": None,
            # tag so cleanup can find ours
            "_brandpdf": 1,
        }
    )
    f.flags.ignore_permissions = True
    f.insert()
    return f.file_url


def cleanup_expired_files():
    """Daily: remove BrandPDF-generated private files older than 1 day.
    Keeps storage bounded; files are regenerated on demand."""
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-1)
    names = frappe.get_all(
        "File",
        filters={
            "is_private": 1,
            "file_name": ("like", "%-brandpdf.pdf"),
            "creation": ("<", cutoff),
        },
        pluck="name",
    )
    for n in names:
        try:
            frappe.delete_doc("File", n, ignore_permissions=True, delete_permanently=True)
        except Exception:
            frappe.log_error(title="BrandPDF cleanup failed")
