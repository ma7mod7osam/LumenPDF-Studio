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
def request_pdf(doctype: str, name: str, template: str = None):
    _authorize(doctype, name)
    # Only honor a template that is a BrandPDF Template for THIS doctype (else ignore -> default).
    if template and not (
        frappe.db.exists("DocType", "BrandPDF Template")
        and frappe.db.exists("BrandPDF Template", {"name": template, "target_doctype": doctype})
    ):
        template = None
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
        template=template,
    )
    return {"job_id": job_id}


@frappe.whitelist()
def list_formats(doctype):
    """Formats available for a doctype (for the download picker). Empty if the caller can't read
    the doctype or the config DocType doesn't exist yet."""
    if not doctype or not frappe.db.exists("DocType", "BrandPDF Template"):
        return []
    if not frappe.has_permission(doctype, "read"):
        return []
    rows = frappe.get_all(
        "BrandPDF Template",
        filters={"target_doctype": doctype},
        fields=["name", "template_name", "is_standard"],
        order_by="is_standard asc, modified desc",
    )
    return [{"name": r["name"], "label": r.get("template_name") or r["name"]} for r in rows]


@frappe.whitelist()
def request_preview(definition, doctype="Quotation", name=None):
    """Render the builder's CURRENT (unsaved) design to a real PDF against a real document, so
    the user gets true WYSIWYG (engine, fonts, pagination). Enqueued like a normal render."""
    _require_manager()
    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, dict):
        frappe.throw("Invalid format definition.")
    _validate_image_srcs(definition)
    if not (doctype and frappe.db.exists("DocType", doctype)):
        frappe.throw("Unknown doctype.")
    if not name:
        recent = frappe.get_all(doctype, order_by="modified desc", limit=1, pluck="name")
        name = recent[0] if recent else None
    if not name:
        frappe.throw(f"No {doctype} document to preview with — create one first.")
    job_id = frappe.generate_hash(length=20)
    set_state(job_id, {"status": "queued"}, frappe.session.user)
    frappe.enqueue(
        "brandpdf.pdf_job.generate_preview",
        queue="long",
        timeout=(config.conf("render_timeout") or 120) + 30,
        job_token=job_id,
        definition=json.dumps(definition),
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


@frappe.whitelist()
def engine_diag():
    """One-click ground truth about the site's PDF engine (System Manager). Open in the browser:
    /api/method/brandpdf.api.engine_diag — reports how the ACTIVE generator treats margins, so
    band-layout issues can be diagnosed from facts instead of guessed from output PDFs."""
    _require_manager()
    import inspect as _inspect
    import io as _io
    from pypdf import PdfReader as _R
    from frappe.utils.pdf import get_pdf as _gp
    from brandpdf.config import conf
    from brandpdf.render.base import get_renderer, default_options
    from brandpdf import compose as _c

    out = {"frappe_version": getattr(frappe, "__version__", "?"),
           "engine_conf": conf("engine") or "(default playwright)",
           "get_pdf_accepts_pdf_generator": "pdf_generator" in _inspect.signature(_gp).parameters,
           "site_pdf_generator": frappe.conf.get("pdf_generator")}
    r = get_renderer()
    out["renderer"] = type(r).__name__

    def pages(html, margin):
        opts = default_options()
        if margin:
            opts["margin"] = margin
        return len(_R(_io.BytesIO(r.render(html, opts))).pages)

    probe = ('<!DOCTYPE html><html><head><style>@page{size:A4;margin:100mm 0mm;}'
             'html,body{margin:0;padding:0;}</style></head>'
             '<body><div style="height:250mm;width:100mm;">probe</div></body></html>')
    full = ('<!DOCTYPE html><html><head><style>@page{size:A4;margin:0;}html,body{margin:0;padding:0;}</style></head>'
            '<body><div style="height:280mm;width:100mm;">tall</div></body></html>')
    try:
        out["probe_100mm_margins_pages"] = pages(probe, {"top": "100mm", "bottom": "100mm", "left": "0mm", "right": "0mm"})
        out["margins_honored"] = out["probe_100mm_margins_pages"] >= 2
    except Exception as e:
        out["probe_error"] = str(e)[:300]
    try:
        out["fullbleed_280mm_pages"] = pages(full, None)  # 1 = full-bleed OK; 2 = forced page margins eat height
    except Exception as e:
        out["fullbleed_error"] = str(e)[:300]
    try:
        out["cached_margin_verdict"] = frappe.cache().get_value("brandpdf_margins_honored")
    except Exception:
        pass
    _c.clear_probe_cache()  # re-probe on the next real render with fresh eyes
    return out


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


@frappe.whitelist()
def doctype_fields(doctype="Quotation"):
    """List a doctype's value-bearing fields so the builder's Field element can offer ANY field.
    Layout/container fieldtypes are skipped; `name` (the ID) is added."""
    _require_manager()
    if not doctype or not frappe.db.exists("DocType", doctype):
        return []
    skip = {
        "Section Break", "Column Break", "Tab Break", "HTML", "Table", "Table MultiSelect",
        "Button", "Heading", "Fold", "Image", "Geolocation", "Signature", "Barcode",
    }
    out = [{"fieldname": "name", "label": "ID (name)"}]
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype in skip or not df.fieldname:
            continue
        out.append({"fieldname": df.fieldname, "label": df.label or df.fieldname})
    return out


@frappe.whitelist()
def child_tables(doctype="Quotation"):
    """List a doctype's child tables and each table's value-bearing fields, so the Data Table
    block can pull rows from ANY child table (items, taxes, payment schedule, custom child tables)."""
    _require_manager()
    if not doctype or not frappe.db.exists("DocType", doctype):
        return []
    colskip = {
        "Section Break", "Column Break", "Tab Break", "HTML", "Table", "Table MultiSelect",
        "Button", "Heading", "Fold", "Image", "Geolocation", "Signature",
    }
    out = []
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype != "Table" or not df.options or not frappe.db.exists("DocType", df.options):
            continue
        try:
            cmeta = frappe.get_meta(df.options)
        except Exception:
            continue
        cols = [{"fieldname": "idx", "label": "#"}]
        for cf in cmeta.fields:
            if cf.fieldtype in colskip or not cf.fieldname or (cf.permlevel or 0) != 0:
                continue  # permlevel>0 fields are permission-gated; don't offer them in a print column
            cols.append({"fieldname": cf.fieldname, "label": cf.label or cf.fieldname})
        out.append({"fieldname": df.fieldname, "label": df.label or df.fieldname,
                    "child_doctype": df.options, "fields": cols})
    return out


@frappe.whitelist()
def builder_doctypes():
    """Candidate doctypes to build formats for (common transaction types that exist + any that
    already have a BrandPDF format)."""
    _require_manager()
    candidates = [
        "Quotation", "Sales Order", "Sales Invoice", "Delivery Note", "POS Invoice",
        "Purchase Order", "Purchase Invoice", "Purchase Receipt", "Supplier Quotation",
        "Payment Entry", "Journal Entry", "Material Request", "Stock Entry", "Lead", "Opportunity",
    ]
    out = [d for d in candidates if frappe.db.exists("DocType", d)]
    if frappe.db.exists("DocType", "BrandPDF Template"):
        for d in frappe.get_all("BrandPDF Template", distinct=True, pluck="target_doctype"):
            if d and d not in out:
                out.append(d)
    return out


@frappe.whitelist()
def builder_docs(doctype, limit=20):
    """Recent documents of a doctype — for the builder's 'preview with real data' picker."""
    _require_manager()
    if not doctype or not frappe.db.exists("DocType", doctype):
        return []
    try:
        return frappe.get_all(doctype, fields=["name"], order_by="modified desc", limit=int(limit), pluck="name")
    except Exception:
        return []


@frappe.whitelist()
def builder_sample(doctype, name):
    """Real document data shaped for the builder's live preview (field values + items/taxes/
    payment schedule)."""
    _require_manager()
    if not (doctype and name and frappe.db.exists(doctype, name)):
        return {}
    from frappe.utils import strip_html_tags
    doc = frappe.get_doc(doctype, name)

    def fmt(f):
        try:
            v = doc.get_formatted(f)
        except Exception:
            v = doc.get(f)
        return "" if v is None else str(v)

    skip = {"Section Break", "Column Break", "Tab Break", "HTML", "Table", "Table MultiSelect",
            "Button", "Image", "Geolocation", "Signature", "Barcode"}
    fields = {"name": doc.name}
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype in skip or not df.fieldname:
            continue
        fields[df.fieldname] = fmt(df.fieldname)

    out = {
        "name": doc.name,
        "transaction_date": fmt("transaction_date") or fmt("posting_date") or fmt("date"),
        "valid_till": fmt("valid_till"),
        "customer_name": fields.get("customer_name") or fields.get("supplier_name") or fields.get("party_name") or fields.get("title") or doc.name,
        "address_display": (doc.get("address_display") or doc.get("supplier_address_display") or doc.get("company_address_display") or ""),
        "total": fmt("total") or fmt("net_total"),
        "grand_total": fmt("grand_total") or fmt("rounded_total") or fmt("total"),
        "fields": fields, "items": [], "taxes": [], "payment_schedule": [],
    }
    for it in (doc.get("items") or []):
        out["items"].append({
            "n": it.get("item_name") or it.get("item_code") or "",
            "q": (f'{it.get_formatted("qty")} {it.get("uom") or it.get("stock_uom") or ""}').strip(),
            "r": it.get_formatted("rate") if it.get("rate") is not None else "",
            "a": it.get_formatted("amount") if it.get("amount") is not None else "",
            "d": strip_html_tags(it.get("description") or "").strip(),
        })
    for tx in (doc.get("taxes") or []):
        if tx.get("tax_amount"):
            out["taxes"].append({"desc": strip_html_tags(tx.get("description") or ""), "amt": tx.get_formatted("tax_amount")})
    for ps in (doc.get("payment_schedule") or []):
        out["payment_schedule"].append({
            "t": ps.get("payment_term") or ps.get("description") or "",
            "due": ps.get_formatted("due_date"), "pct": ps.get_formatted("invoice_portion"), "amt": ps.get_formatted("payment_amount"),
        })

    # Generic child-table rows (all child tables, all displayable fields, formatted) for the Data Table block.
    tables = {}
    colskip = {"Section Break", "Column Break", "Tab Break", "HTML", "Table", "Table MultiSelect",
               "Button", "Image", "Geolocation", "Signature"}
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype != "Table" or not df.options or not frappe.db.exists("DocType", df.options):
            continue
        try:
            cmeta = frappe.get_meta(df.options)
        except Exception:
            continue
        cfields = [cf.fieldname for cf in cmeta.fields
                   if cf.fieldtype not in colskip and cf.fieldname and (cf.permlevel or 0) == 0]
        rows = []
        for row in (doc.get(df.fieldname) or []):
            rd = {"idx": row.idx}
            for cf in cfields:
                try:
                    v = row.get_formatted(cf)
                except Exception:
                    v = row.get(cf)
                rd[cf] = "" if v is None else strip_html_tags(str(v)).strip()
            rows.append(rd)
        tables[df.fieldname] = rows
    out["tables"] = tables
    return out


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
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    # Honor the standard 'print' permission too — don't be weaker than the stock Print button.
    if not frappe.has_permission(doctype, "print", doc=doc):
        frappe.throw("You are not permitted to print this document.", frappe.PermissionError)


def _key(job_id: str) -> str:
    return f"brandpdf:job:{job_id}"


def set_state(job_id: str, state: dict, user: str):
    """Persist job state with the owning user stamped in (used by the worker too)."""
    frappe.cache().set_value(_key(job_id), {**state, "_user": user}, expires_in_sec=900)


def _get_state(job_id: str):
    return frappe.cache().get_value(_key(job_id))
