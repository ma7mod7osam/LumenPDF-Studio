"""Whitelisted endpoints. Rendering is ENQUEUED (never run in the web process) so a
managed box can't be OOM'd by concurrent clicks (PLAN H7). The button POSTs via
frappe.call and polls for a private, user-scoped file URL (PLAN H6).

Enabled doctypes are resolved from BrandPDF Mapping (Phase 2), falling back to ["Quotation"].
No client-supplied template path (B1). Job result is scoped to the requesting user (B2).
"""
import json

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
        job_token=job_id,  # NOTE: 'job_id' is reserved by frappe.enqueue, so pass ours as 'job_token'
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


# --- visual builder: save / load formats -----------------------------------

@frappe.whitelist()
def save_format(definition, name=None):
    """Persist a builder design as a BrandPDF Template (source_type=blocks) and make it the
    active format for its target doctype. System Manager only (templates affect all printing)."""
    _require_manager()
    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, dict):
        frappe.throw("Invalid format definition.")
    tmpl_name = (name or definition.get("name") or "Custom Format").strip()
    if not tmpl_name:
        frappe.throw("Give the format a name.")
    target = definition.get("target_doctype") or "Quotation"
    _validate_image_srcs(definition)
    payload = json.dumps(definition)

    if frappe.db.exists("BrandPDF Template", tmpl_name):
        t = frappe.get_doc("BrandPDF Template", tmpl_name)
        if t.get("is_standard"):
            frappe.throw("That name is a standard template. Use a different name.")
        if t.get("source_type") and t.source_type != "blocks":
            frappe.throw(
                f"A template named '{tmpl_name}' already exists as a {t.source_type} template. "
                "Choose a different name so it isn't overwritten."
            )
        t.target_doctype = target
        t.source_type = "blocks"
        t.definition = payload
        t.flags.ignore_permissions = True
        t.save()
    else:
        t = frappe.get_doc({
            "doctype": "BrandPDF Template", "template_name": tmpl_name, "target_doctype": target,
            "source_type": "blocks", "is_standard": 0, "definition": payload,
        })
        t.flags.ignore_permissions = True
        t.insert()

    _activate_mapping(target, tmpl_name)
    frappe.db.commit()
    return {"name": tmpl_name, "target_doctype": target, "activated": True}


@frappe.whitelist()
def get_format(name=None, target_doctype="Quotation"):
    """Return a saved design to load into the builder. With a name, that template; otherwise the
    active design for the doctype (so the builder opens on what's currently live)."""
    _require_manager()
    if name and frappe.db.exists("BrandPDF Template", name):
        t = frappe.get_doc("BrandPDF Template", name)
        if t.get("definition"):
            return {"name": t.name, "definition": json.loads(t.definition)}
    maps = frappe.get_all(
        "BrandPDF Mapping", filters={"target_doctype": target_doctype, "enabled": 1},
        fields=["template"], order_by="priority asc", limit=1,
    )
    if maps:
        t = frappe.get_doc("BrandPDF Template", maps[0]["template"])
        if t.get("definition"):
            return {"name": t.name, "definition": json.loads(t.definition)}
    return {"name": None, "definition": None}


def _require_manager():
    if "System Manager" not in frappe.get_roles():
        frappe.throw("Only System Manager can edit print formats.", frappe.PermissionError)


def _validate_image_srcs(definition):
    """Images must be uploaded site files (/files/..), not arbitrary URLs — so a saved design
    can't make the render worker fetch a remote/internal URL (SSRF)."""
    srcs = []
    dbr = (definition.get("branding") or {}) if isinstance(definition, dict) else {}
    for k in ("header_image", "footer_image"):
        if dbr.get(k):
            srcs.append(dbr[k])
    for bl in (definition.get("blocks") or []):
        if isinstance(bl, dict) and bl.get("type") == "image":
            s = (bl.get("settings") or {}).get("src")
            if s:
                srcs.append(s)
    for s in srcs:
        s = str(s).strip()
        if s and not (s.startswith("/files/") or s.startswith("/private/files/")):
            frappe.throw(f"Images must be uploaded files (path starting /files/). Got: {s[:80]}")


def _activate_mapping(target, tmpl_name):
    existing = frappe.get_all(
        "BrandPDF Mapping", filters={"target_doctype": target}, pluck="name", order_by="priority asc", limit=1
    )
    if existing:
        m = frappe.get_doc("BrandPDF Mapping", existing[0])
        m.template = tmpl_name
        m.enabled = 1
        m.flags.ignore_permissions = True
        m.save()
    else:
        m = frappe.get_doc({"doctype": "BrandPDF Mapping", "target_doctype": target, "template": tmpl_name, "enabled": 1, "priority": 0})
        m.flags.ignore_permissions = True
        m.insert()


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
