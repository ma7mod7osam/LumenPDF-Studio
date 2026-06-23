"""Whitelisted endpoints. Rendering is ENQUEUED (never run in the web process) so a
managed box can't be OOM'd by concurrent clicks (PLAN H7). The button POSTs via
frappe.call and polls for a private, user-scoped file URL (PLAN H6)."""
import frappe

# Phase 1 allowlist. Phase 2 derives this from enabled BrandPDF Mapping rows.
ALLOWED_DOCTYPES = {"Quotation"}


@frappe.whitelist()
def request_pdf(doctype: str, name: str, template: str = None):
    _authorize(doctype, name)
    job_id = frappe.generate_hash(length=20)
    _set_state(job_id, {"status": "queued"})
    frappe.enqueue(
        "brandpdf.pdf_job.generate",
        queue="long",
        timeout=180,
        job_id=job_id,
        doctype=doctype,
        docname=name,
        template=template,
        user=frappe.session.user,
    )
    return {"job_id": job_id}


@frappe.whitelist()
def get_job_result(job_id: str):
    return _get_state(job_id) or {"status": "unknown"}


# --- internals -------------------------------------------------------------

def _authorize(doctype: str, name: str):
    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.PermissionError)
    if doctype not in ALLOWED_DOCTYPES:
        frappe.throw(f"BrandPDF is not enabled for {doctype}.", frappe.PermissionError)
    # Enforces read perm AND field-level permlevel (template authors must not embed
    # permlevel-restricted fields — see docs).
    frappe.get_doc(doctype, name).check_permission("read")


def _key(job_id: str) -> str:
    return f"brandpdf:job:{job_id}"


def _set_state(job_id: str, state: dict):
    frappe.cache().set_value(_key(job_id), state, expires_in_sec=900)


def _get_state(job_id: str):
    return frappe.cache().get_value(_key(job_id))
