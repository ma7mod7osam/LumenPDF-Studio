"""Whitelisted endpoints. Rendering is ENQUEUED (never run in the web process) so a
managed box can't be OOM'd by concurrent clicks (PLAN H7). The button POSTs via
frappe.call and polls for a private, user-scoped file URL (PLAN H6).

Enabled doctypes are resolved from BrandPDF Mapping (Phase 2), falling back to ["Quotation"].
No client-supplied template path (B1). Job result is scoped to the requesting user (B2).
"""
import frappe

from brandpdf import config


@frappe.whitelist()
def request_pdf(doctype: str, name: str):
    _authorize(doctype, name)
    job_id = frappe.generate_hash(length=20)
    set_state(job_id, {"status": "queued"}, frappe.session.user)
    frappe.enqueue(
        "brandpdf.pdf_job.generate",
        queue="long",
        timeout=(config.conf("render_timeout") or 120) + 30,
        job_id=job_id,
        doctype=doctype,
        docname=name,
        user=frappe.session.user,
    )
    return {"job_id": job_id}


@frappe.whitelist()
def get_job_result(job_id: str):
    state = _get_state(job_id)
    if not state:
        return {"status": "unknown"}
    if state.get("_user") != frappe.session.user:
        frappe.throw("Not found.", frappe.PermissionError)
    return {k: v for k, v in state.items() if k != "_user"}


@frappe.whitelist()
def enabled_doctypes():
    """Used by the form button to know where to render itself. Filtered to doctypes the
    caller can read, so the button never appears where a click would 403 (review #7)."""
    from brandpdf import resolver
    return [dt for dt in resolver.enabled_doctypes() if frappe.has_permission(dt, "read")]


# --- internals -------------------------------------------------------------

def _authorize(doctype: str, name: str):
    from brandpdf import resolver

    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.PermissionError)
    if doctype not in resolver.enabled_doctypes():
        frappe.throw(f"BrandPDF is not enabled for {doctype}.", frappe.PermissionError)
    frappe.get_doc(doctype, name).check_permission("read")


def _key(job_id: str) -> str:
    return f"brandpdf:job:{job_id}"


def set_state(job_id: str, state: dict, user: str):
    """Persist job state with the owning user stamped in (used by the worker too)."""
    frappe.cache().set_value(_key(job_id), {**state, "_user": user}, expires_in_sec=900)


def _get_state(job_id: str):
    return frappe.cache().get_value(_key(job_id))
