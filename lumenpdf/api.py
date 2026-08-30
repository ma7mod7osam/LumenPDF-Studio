"""Whitelisted endpoints. Rendering is ENQUEUED (never run in the web process) so a
managed box can't be OOM'd by concurrent clicks (PLAN H7). The button POSTs via
frappe.call and polls for a private, user-scoped file URL (PLAN H6).

Enabled doctypes are resolved from LumenPDF Mapping (Phase 2), falling back to ["Quotation"].
No client-supplied template path (B1). Job result is scoped to the requesting user (B2).
"""
import json

import frappe

from lumenpdf import config


@frappe.whitelist()
def request_pdf(doctype: str, name: str, template: str = None):
    _authorize(doctype, name)
    # Only honor a template that is a LumenPDF Template for THIS doctype (else ignore -> default).
    if template and not (
        frappe.db.exists("DocType", "LumenPDF Template")
        and frappe.db.exists("LumenPDF Template", {"name": template, "target_doctype": doctype})
    ):
        template = None
    job_id = frappe.generate_hash(length=20)
    set_state(job_id, {"status": "queued"}, frappe.session.user)
    frappe.enqueue(
        "lumenpdf.pdf_job.generate",
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
def list_formats(doctype=None, company=None, report_name=None):
    """Formats available for a doctype (or, when report_name is given, for a report — the builder
    then sends NO doctype). `company` scopes which doctype format is marked default. Empty if the
    caller can't read the target or the config DocType doesn't exist yet."""
    if report_name:
        if not frappe.db.exists("DocType", "LumenPDF Template"):
            return []
        try:
            rows = frappe.get_all("LumenPDF Template",
                                  filters={"target_kind": "report", "report_name": report_name},
                                  fields=["name", "template_name", "is_standard", "source_type"],
                                  order_by="is_standard asc, modified desc")
        except Exception:
            return []  # target_kind/report_name columns not migrated yet
        default = _default_report_template(report_name)
        out = [{"name": r["name"], "label": r.get("template_name") or r["name"],
                "is_standard": bool(r.get("is_standard")), "is_default": (r["name"] == default),
                "is_visual": (r.get("source_type") or "blocks") == "blocks"} for r in rows]
        out.sort(key=lambda x: (not x["is_default"]))
        return out
    if not doctype or not frappe.db.exists("DocType", "LumenPDF Template"):
        return []
    if not frappe.has_permission(doctype, "read"):
        return []
    rows = frappe.get_all(
        "LumenPDF Template",
        filters={"target_doctype": doctype},
        fields=["name", "template_name", "is_standard", "source_type"],
        order_by="is_standard asc, modified desc",
    )
    default = _default_template(doctype, company)
    out = [{
        "name": r["name"], "label": r.get("template_name") or r["name"],
        "is_standard": bool(r.get("is_standard")), "is_default": (r["name"] == default),
        "is_visual": (r.get("source_type") or "blocks") == "blocks",  # jinja/body can't open on the canvas
    } for r in rows]
    out.sort(key=lambda x: (not x["is_default"]))  # the default format first (for the picker preselect)
    return out


def _default_template(doctype, company=None):
    """The doctype's default template: the doc's COMPANY-scoped mapping wins, else the global
    (blank-company) mapping; None if neither. Selection happens in PYTHON, not SQL filters —
    legacy rows have company = NULL and `IN ('', NULL)` never matches NULL in SQL; and another
    company's mapping must never leak in as a fallback."""
    if not frappe.db.exists("DocType", "LumenPDF Mapping"):
        return None
    try:
        rows = frappe.get_all("LumenPDF Mapping", filters={"target_doctype": doctype, "enabled": 1},
                              fields=["template", "company"], order_by="priority asc, creation asc")
    except Exception:
        try:  # old install: company column not migrated yet -> every row is global
            rows = frappe.get_all("LumenPDF Mapping", filters={"target_doctype": doctype, "enabled": 1},
                                  fields=["template"], order_by="priority asc, creation asc")
            return rows[0]["template"] if rows else None
        except Exception:
            return None
    if company:
        for r in rows:
            if (r.get("company") or "") == company:
                return r["template"]
    for r in rows:
        if not r.get("company"):  # NULL or "" -> global
            return r["template"]
    return None


def _default_report_template(report_name):
    """The active report template (from the enabled report mapping), or None."""
    try:
        rows = frappe.get_all("LumenPDF Mapping",
                              filters={"target_kind": "report", "report_name": report_name, "enabled": 1},
                              fields=["template"], order_by="priority asc, creation asc", limit=1)
        return rows[0]["template"] if rows else None
    except Exception:
        return None


@frappe.whitelist()
def list_companies():
    """Companies for the Formats manager's scope picker (empty on non-ERPNext sites)."""
    _require_manager()
    if not frappe.db.exists("DocType", "Company"):
        return []
    return frappe.get_all("Company", pluck="name", order_by="name asc")


@frappe.whitelist()
def set_default_format(doctype, template, company=None):
    """Make `template` the default format for `doctype` — globally (company empty) or for ONE
    company in a multi-company setup. System-Manager only."""
    _require_manager()
    _ensure_config_ready()
    company = (company or "").strip() or None
    if not (doctype and template and frappe.db.exists("LumenPDF Template", template)):
        frappe.throw("Unknown format.")
    if company and not frappe.db.exists("Company", company):
        frappe.throw("Unknown company.")
    t = frappe.get_doc("LumenPDF Template", template)
    if t.target_doctype and t.target_doctype != doctype:
        frappe.throw("That format belongs to a different doctype.")
    # Find THIS scope's existing row in Python (legacy global rows have company = NULL, which
    # SQL 'IN' filters never match — a filter-based lookup would create a duplicate mapping).
    try:
        rows = frappe.get_all("LumenPDF Mapping", filters={"target_doctype": doctype},
                              fields=["name", "company"], order_by="priority asc, creation asc")
    except Exception:
        rows = [{"name": n, "company": None} for n in frappe.get_all(
            "LumenPDF Mapping", filters={"target_doctype": doctype}, pluck="name",
            order_by="priority asc, creation asc")]
    existing = None
    for r in rows:
        rc = r.get("company") or ""
        if (company and rc == company) or (not company and not rc):
            existing = r["name"]
            break
    if existing:
        m = frappe.get_doc("LumenPDF Mapping", existing)
        m.template = template
        m.company = company or ""
        m.enabled = 1
        m.flags.ignore_permissions = True
        m.save()
    else:
        m = frappe.get_doc({"doctype": "LumenPDF Mapping", "target_doctype": doctype,
                            "template": template, "company": company or "", "enabled": 1, "priority": 0})
        m.flags.ignore_permissions = True
        m.insert()
    # Self-heal: if a concurrent call (or an old bug) left extra rows in the SAME scope, keep the
    # row we just wrote and drop the rest — the winner is deterministic, not creation-order luck.
    try:
        for r in frappe.get_all("LumenPDF Mapping", filters={"target_doctype": doctype},
                                fields=["name", "company"]):
            rc = r.get("company") or ""
            same_scope = (company and rc == company) or (not company and not rc)
            if same_scope and r["name"] != m.name:
                frappe.delete_doc("LumenPDF Mapping", r["name"], ignore_permissions=True)
    except Exception:
        pass
    frappe.db.commit()
    return {"default": template, "company": company or ""}


@frappe.whitelist()
def set_default_report_format(report_name, template):
    """Make `template` the active branded format for a report (used by the 'Branded PDF' button
    and, when replace_report_pdf is on, the native Report > PDF). System-Manager only."""
    _require_manager()
    _ensure_config_ready()
    if not (report_name and template and frappe.db.exists("LumenPDF Template", template)):
        frappe.throw("Unknown format.")
    ref = frappe.db.get_value("Report", report_name, "ref_doctype") or "Report"
    try:
        rows = frappe.get_all("LumenPDF Mapping", filters={"target_kind": "report", "report_name": report_name},
                              fields=["name"], order_by="priority asc, creation asc")
    except Exception:
        rows = []
    if rows:
        m = frappe.get_doc("LumenPDF Mapping", rows[0]["name"])
        m.template = template
        m.enabled = 1
        m.replace_report_pdf = 1
        m.flags.ignore_permissions = True
        m.save()
        for r in rows[1:]:  # collapse any duplicate report rows onto the one we just wrote
            frappe.delete_doc("LumenPDF Mapping", r["name"], ignore_permissions=True)
    else:
        m = frappe.get_doc({"doctype": "LumenPDF Mapping", "target_kind": "report", "report_name": report_name,
                            "target_doctype": ref, "template": template, "enabled": 1, "priority": 0,
                            "replace_report_pdf": 1})
        m.flags.ignore_permissions = True
        m.insert()
    frappe.db.commit()
    return {"default": template, "report_name": report_name}


@frappe.whitelist()
def duplicate_format(name, new_name=None):
    """Copy a saved format to a new one (a fresh, non-standard, non-gallery copy). Returns the new
    name (made unique if needed). System-Manager only."""
    _require_manager()
    if not frappe.db.exists("LumenPDF Template", name):
        frappe.throw("Unknown format.")
    src = frappe.get_doc("LumenPDF Template", name)
    base = (new_name or "").strip() or ((src.template_name or name) + " copy")
    nm, i = base, 2
    while frappe.db.exists("LumenPDF Template", nm):  # unique name (autoname = template_name)
        nm, i = f"{base} {i}", i + 1
    definition = src.get("definition")
    try:  # keep the name inside the definition JSON in sync
        d = json.loads(definition) if isinstance(definition, str) else definition
        if isinstance(d, dict):
            d["name"] = nm
            definition = json.dumps(d)
    except Exception:
        pass
    t = frappe.get_doc({
        "doctype": "LumenPDF Template", "template_name": nm, "target_doctype": src.target_doctype,
        "source_type": src.get("source_type") or "blocks", "is_standard": 0, "in_gallery": 0,
        "definition": definition, "body": src.get("body"), "jinja_path": src.get("jinja_path"),
    })
    t.flags.ignore_permissions = True
    t.insert()
    frappe.db.commit()
    return {"name": nm, "target_doctype": src.target_doctype}


@frappe.whitelist()
def delete_format(name):
    """Delete a custom (non-standard) format. If it was the default, repoint the mapping to another
    format for the same doctype, or disable it so printing falls back to native. System-Manager only."""
    _require_manager()
    if not frappe.db.exists("LumenPDF Template", name):
        return {"deleted": False}
    t = frappe.get_doc("LumenPDF Template", name)
    if t.get("is_standard"):
        frappe.throw("Standard formats can't be deleted (duplicate them to edit).")
    target = t.target_doctype
    maps = frappe.get_all(
        "LumenPDF Mapping", filters={"target_doctype": target, "template": name}, pluck="name"
    ) if frappe.db.exists("DocType", "LumenPDF Mapping") else []
    frappe.delete_doc("LumenPDF Template", name, ignore_permissions=True)
    # Replacement for orphaned mappings: prefer the doctype's surviving GLOBAL default (keeps a
    # company scope consistent with the site-wide look), else any surviving format.
    global_default = _default_template(target)
    if global_default == name:
        global_default = None
    for mn in maps:  # this format was a default -> keep printing working
        m = frappe.get_doc("LumenPDF Mapping", mn)
        others = [global_default] if global_default else frappe.get_all(
            "LumenPDF Template", filters={"target_doctype": target, "name": ("!=", name)},
            pluck="name", order_by="is_standard asc, modified desc", limit=1,
        )
        if others:
            m.template = others[0]
        else:
            m.enabled = 0  # nothing left -> native PDF takes over
        m.flags.ignore_permissions = True
        m.save()
    frappe.db.commit()
    return {"deleted": True, "target_doctype": target}


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
        "lumenpdf.pdf_job.generate_preview",
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
    from lumenpdf import resolver
    return [dt for dt in resolver.enabled_doctypes() if frappe.has_permission(dt, "read")]


@frappe.whitelist()
def engine_diag():
    """One-click ground truth about the site's PDF engine (System Manager). Open in the browser:
    /api/method/lumenpdf.api.engine_diag — reports how the ACTIVE generator treats margins, so
    band-layout issues can be diagnosed from facts instead of guessed from output PDFs."""
    _require_manager()
    import inspect as _inspect
    import io as _io
    from pypdf import PdfReader as _R
    from frappe.utils.pdf import get_pdf as _gp
    from lumenpdf.config import conf
    from lumenpdf.render.base import get_renderer, default_options
    from lumenpdf import compose as _c

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

    PF100 = '<style>.print-format{margin-top:100mm;margin-bottom:100mm;margin-left:0mm;margin-right:0mm;}</style>'
    PF0 = '<style>.print-format{margin-top:0mm;margin-bottom:0mm;margin-left:0mm;margin-right:0mm;}</style>'
    probe = ('<!DOCTYPE html><html><head><style>@page{size:A4;margin:100mm 0mm;}'
             'html,body{margin:0;padding:0;}</style>' + PF100 + '</head>'
             '<body><div style="height:250mm;width:100mm;">probe</div></body></html>')
    full = ('<!DOCTYPE html><html><head><style>@page{size:A4;margin:0;}html,body{margin:0;padding:0;}</style>'
            + PF0 + '</head><body><div style="height:280mm;width:100mm;">tall</div></body></html>')
    pf_only = ('<!DOCTYPE html><html><head>' + PF100 +
               '</head><body><div style="height:250mm;width:100mm;">probe</div></body></html>')
    try:
        out["probe_100mm_margins_pages"] = pages(probe, {"top": "100mm", "bottom": "100mm", "left": "0mm", "right": "0mm"})
        out["margins_honored"] = out["probe_100mm_margins_pages"] >= 2
    except Exception as e:
        out["probe_error"] = str(e)[:300]
    try:
        out["pf_channel_only_pages"] = pages(pf_only, None)  # >=2 = the .print-format CSS channel works alone
    except Exception as e:
        out["pf_channel_error"] = str(e)[:300]
    try:
        out["fullbleed_280mm_pages"] = pages(full, None)  # 1 = full-bleed OK; 2 = forced page margins eat height
    except Exception as e:
        out["fullbleed_error"] = str(e)[:300]
    try:
        out["cached_margin_verdict"] = frappe.cache().get_value("lumenpdf_margins_honored")
    except Exception:
        pass
    try:
        # Landscape end-to-end: with the renderer's wkhtml fallback this reports what the
        # user actually gets, not just what the chrome generator supports.
        opts = default_options()
        opts["page_width_mm"], opts["page_height_mm"] = 297.0, 210.0
        p = _R(_io.BytesIO(r.render("<!DOCTYPE html><html><body>landscape probe</body></html>", opts))).pages[0]
        out["landscape_page_mm"] = f"{float(p.mediabox.width) * 25.4 / 72:.0f}x{float(p.mediabox.height) * 25.4 / 72:.0f}"
        out["landscape_honored"] = float(p.mediabox.width) > float(p.mediabox.height)
        out["chrome_landscape_verdict"] = frappe.cache().get_value("lumenpdf_chrome_landscape")
    except Exception as e:
        out["landscape_error"] = str(e)[:300]
    _c.clear_probe_cache()  # re-probe on the next real render with fresh eyes
    return out


# --- visual builder: save / load formats -----------------------------------

@frappe.whitelist()
def save_format(definition, name=None):
    """Persist a builder design as a LumenPDF Template (source_type=blocks) and make it the
    active format for its target doctype. System Manager only (templates affect all printing)."""
    _require_manager()
    _ensure_config_ready()
    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, dict):
        frappe.throw("Invalid format definition.")
    tmpl_name = (name or definition.get("name") or "Custom Format").strip()
    if not tmpl_name:
        frappe.throw("Give the format a name.")
    kind = "report" if (definition.get("target_kind") == "report") else "doctype"
    report_name = (definition.get("report_name") or "").strip() if kind == "report" else ""
    if kind == "report":
        if not report_name or not frappe.db.exists("Report", report_name):
            frappe.throw("Choose a report for this report format.")
        # target_doctype stays a real DocType (the field is a required Link) — use the report's
        # reference doctype so the row validates; report resolution keys off report_name/target_kind.
        target = frappe.db.get_value("Report", report_name, "ref_doctype") or "Report"
    else:
        target = definition.get("target_doctype") or "Quotation"
    _validate_image_srcs(definition)
    payload = json.dumps(definition)

    if frappe.db.exists("LumenPDF Template", tmpl_name):
        t = frappe.get_doc("LumenPDF Template", tmpl_name)
        if t.get("is_standard"):
            frappe.throw("That name is a standard template. Use a different name.")
        if t.get("source_type") and t.source_type != "blocks":
            frappe.throw(
                f"A template named '{tmpl_name}' already exists as a {t.source_type} template. "
                "Choose a different name so it isn't overwritten."
            )
        t.target_doctype = target
        t.target_kind = kind
        t.report_name = report_name or None
        t.source_type = "blocks"
        t.definition = payload
        t.flags.ignore_permissions = True
        t.save()
    else:
        t = frappe.get_doc({
            "doctype": "LumenPDF Template", "template_name": tmpl_name, "target_doctype": target,
            "target_kind": kind, "report_name": report_name or None,
            "source_type": "blocks", "is_standard": 0, "definition": payload,
        })
        t.flags.ignore_permissions = True
        t.insert()

    if kind == "report":
        _activate_report_mapping(report_name, tmpl_name, target)
    else:
        _activate_mapping(target, tmpl_name)
    frappe.db.commit()
    return {"name": tmpl_name, "target_doctype": target, "target_kind": kind,
            "report_name": report_name, "activated": True}


# --- feedback ---------------------------------------------------------------

@frappe.whitelist()
def submit_feedback(message, reply_to=None):
    """Send builder feedback to the app maintainers by email (site_config
    `lumenpdf_feedback_email` overrides the default). Queued through the site's own outgoing
    email; context (site, user, version) is attached so reports are actionable."""
    _require_manager()
    msg = (message or "").strip()
    if not msg:
        frappe.throw("Write something first.")
    msg = msg[:5000]
    reply_to = (reply_to or "").strip() or None
    if reply_to and not frappe.utils.validate_email_address(reply_to):
        reply_to = None
    to = (frappe.conf.get("lumenpdf_feedback_email")
          or frappe.conf.get("brandpdf_feedback_email")  # legacy (pre-rename) key
          or "support@bstc-bh.com")
    try:
        from lumenpdf import __version__ as _v
    except Exception:
        _v = "?"
    ctx = (f"Site: {getattr(frappe.local, 'site', '?')}\n"
           f"User: {frappe.session.user}\n"
           f"App: lumenpdf v{_v}\n"
           f"Reply-to: {reply_to or '-'}")
    try:
        frappe.sendmail(
            recipients=[to],
            subject=f"LumenPDF Studio feedback — {getattr(frappe.local, 'site', '?')}",
            message=f"<pre style='font-family:inherit;white-space:pre-wrap'>{frappe.utils.escape_html(msg)}</pre>"
                    f"<hr><pre style='color:#666'>{frappe.utils.escape_html(ctx)}</pre>",
            reply_to=reply_to,
        )
    except Exception:
        frappe.log_error(title="LumenPDF feedback send failed", message=frappe.get_traceback())
        frappe.throw("Could not queue the email — check this site's outgoing email settings.")
    return {"ok": True}


# --- reusable block snippets ("My blocks") ---------------------------------

@frappe.whitelist()
def list_snippets():
    """Saved reusable blocks, newest first. Each carries the full block JSON so the builder can
    insert without a second round-trip."""
    _require_manager()
    if not frappe.db.exists("DocType", "LumenPDF Snippet"):
        return []
    out = []
    for r in frappe.get_all("LumenPDF Snippet", fields=["name", "snippet_name", "block"],
                            order_by="modified desc", limit=200):
        try:
            blk = json.loads(r["block"]) if r.get("block") else None
        except Exception:
            blk = None
        if isinstance(blk, dict) and blk.get("type"):
            out.append({"name": r["name"], "label": r.get("snippet_name") or r["name"], "block": blk})
    return out


@frappe.whitelist()
def save_snippet(name, block):
    """Save ONE configured block (settings+style; rows include their children) for reuse across
    formats. Same-name saves overwrite. System-Manager only; image paths keep the /files rule."""
    _require_manager()
    _ensure_config_ready()
    if isinstance(block, str):
        block = json.loads(block)
    if not isinstance(block, dict) or not block.get("type"):
        frappe.throw("Invalid block.")
    _validate_block_images(block)
    nm = (name or "").strip() or "Block"
    payload = json.dumps(block)
    if frappe.db.exists("LumenPDF Snippet", nm):
        d = frappe.get_doc("LumenPDF Snippet", nm)
        d.block = payload
        d.flags.ignore_permissions = True
        d.save()
    else:
        d = frappe.get_doc({"doctype": "LumenPDF Snippet", "snippet_name": nm, "block": payload})
        d.flags.ignore_permissions = True
        d.insert()
    frappe.db.commit()
    return {"name": nm}


@frappe.whitelist()
def delete_snippet(name):
    _require_manager()
    if frappe.db.exists("LumenPDF Snippet", name):
        frappe.delete_doc("LumenPDF Snippet", name, ignore_permissions=True)
        frappe.db.commit()
    return {"deleted": True}


def _validate_block_images(block):
    """Image srcs inside a snippet obey the same uploaded-files-only rule as formats (SSRF)."""
    def walk(bl):
        if not isinstance(bl, dict):
            return
        if bl.get("type") == "image":
            s = (bl.get("settings") or {}).get("src")
            if s and not (str(s).startswith("/files/") or str(s).startswith("/private/files/")):
                frappe.throw(f"Images must be uploaded files (path starting /files/). Got: {str(s)[:80]}")
        for cell in ((bl.get("settings") or {}).get("cells") or []):
            if isinstance(cell, list):
                for c in cell:
                    walk(c)
    walk(block)


@frappe.whitelist()
def set_gallery(name, on):
    """Publish/unpublish a saved format to this site's Templates gallery (visible to every
    builder user on the site as a starting point). System-Manager only."""
    _require_manager()
    if not frappe.db.exists("LumenPDF Template", name):
        frappe.throw("Unknown format.")
    t = frappe.get_doc("LumenPDF Template", name)
    if not t.get("definition"):
        frappe.throw("Only visual (builder) formats can be published to the gallery.")
    t.in_gallery = 1 if str(on) in ("1", "true", "True") else 0
    t.flags.ignore_permissions = True
    t.flags.lumenpdf_allow_standard_edit = True  # flag change only; body stays read-only
    t.save()
    frappe.db.commit()
    return {"name": name, "in_gallery": bool(t.in_gallery)}


@frappe.whitelist()
def gallery_list():
    """Site templates published to the gallery (name/label/target only — definitions load on
    pick via get_format)."""
    _require_manager()
    if not frappe.db.exists("DocType", "LumenPDF Template"):
        return []
    try:
        rows = frappe.get_all(
            "LumenPDF Template",
            filters={"in_gallery": 1},
            fields=["name", "template_name", "target_doctype"],
            order_by="modified desc",
        )
    except Exception:
        return []  # in_gallery column not migrated yet
    return [{"name": r["name"], "label": r.get("template_name") or r["name"],
             "target": r.get("target_doctype") or ""} for r in rows]


@frappe.whitelist()
def get_format(name=None, target_doctype="Quotation", report_name=None):
    """Return a saved design to load into the builder. With a name, that template; else the active
    design for the report (report_name) or the doctype — so the builder opens on what's live."""
    _require_manager()
    if name:
        # An explicit name NEVER falls through to some other format: silently loading the
        # doctype's default instead made "Open" look like it did nothing / didn't switch.
        if not frappe.db.exists("LumenPDF Template", name):
            return {"name": None, "definition": None, "reason": "missing"}
        t = frappe.get_doc("LumenPDF Template", name)
        if t.get("definition"):
            return {"name": t.name, "definition": json.loads(t.definition)}
        return {"name": t.name, "definition": None,
                "reason": "not_visual" if (t.get("source_type") or "blocks") != "blocks" else "empty"}
    if report_name:
        try:
            maps = frappe.get_all(
                "LumenPDF Mapping", filters={"target_kind": "report", "report_name": report_name, "enabled": 1},
                fields=["template"], order_by="priority asc", limit=1,
            )
        except Exception:
            maps = []
        if maps:
            t = frappe.get_doc("LumenPDF Template", maps[0]["template"])
            if t.get("definition"):
                return {"name": t.name, "definition": json.loads(t.definition)}
        return {"name": None, "definition": None}
    if not _ensure_config_ready():
        return {"name": None, "definition": None}
    maps = frappe.get_all(
        "LumenPDF Mapping", filters={"target_doctype": target_doctype, "enabled": 1},
        fields=["template"], order_by="priority asc", limit=1,
    )
    if maps:
        t = frappe.get_doc("LumenPDF Template", maps[0]["template"])
        if t.get("definition"):
            return {"name": t.name, "definition": json.loads(t.definition)}
    return {"name": None, "definition": None}


@frappe.whitelist()
def builder_reports(limit=300):
    """Reports the current user can build a branded format for (Query/Script/Report Builder)."""
    _require_manager()
    if not frappe.db.exists("DocType", "Report"):
        return []
    try:
        rows = frappe.get_all("Report", filters={"disabled": 0},
                              fields=["name", "report_name", "ref_doctype", "report_type"],
                              order_by="modified desc", limit=int(limit))
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            if not frappe.has_permission("Report", "read", doc=r["name"]):
                continue
        except Exception:
            pass
        out.append({"name": r["name"], "label": r.get("report_name") or r["name"],
                    "ref_doctype": r.get("ref_doctype") or "", "report_type": r.get("report_type") or ""})
    return out


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
    out = [{"fieldname": "name", "label": "ID (name)", "fieldtype": "Data"}]
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype in skip or not df.fieldname:
            continue
        out.append({"fieldname": df.fieldname, "label": df.label or df.fieldname, "fieldtype": df.fieldtype})
    return out


@frappe.whitelist()
def doctype_link_fields(doctype="Quotation"):
    """For each Link field on the doctype, the linked doctype's value-bearing (permlevel-0) fields,
    so the builder's Field block can offer one-hop cross-doctype paths like `customer.email_id`.
    Only links + targets the caller may read; permlevel>0 fields are never offered."""
    _require_manager()
    if not doctype or not frappe.db.exists("DocType", doctype):
        return []
    skip = {
        "Section Break", "Column Break", "Tab Break", "HTML", "Table", "Table MultiSelect",
        "Button", "Heading", "Fold", "Image", "Geolocation", "Signature", "Barcode",
    }
    out = []
    seen = set()
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype != "Link" or not df.options or (df.permlevel or 0) != 0:
            continue
        if df.fieldname in seen or not frappe.db.exists("DocType", df.options):
            continue
        seen.add(df.fieldname)
        try:
            if not frappe.has_permission(df.options, "read"):
                continue  # don't expose paths into doctypes the user can't read
            tmeta = frappe.get_meta(df.options)
        except Exception:
            continue
        fields = [{"fieldname": "name", "label": "ID (name)", "fieldtype": "Data"}]
        for tf in tmeta.fields:
            if tf.fieldtype in skip or not tf.fieldname or (tf.permlevel or 0) != 0:
                continue
            fields.append({"fieldname": tf.fieldname, "label": tf.label or tf.fieldname, "fieldtype": tf.fieldtype})
        if len(fields) > 1:
            out.append({"link_field": df.fieldname, "link_label": df.label or df.fieldname,
                        "target_doctype": df.options, "fields": fields})
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
    already have a LumenPDF format)."""
    _require_manager()
    candidates = [
        "Quotation", "Sales Order", "Sales Invoice", "Delivery Note", "POS Invoice",
        "Purchase Order", "Purchase Invoice", "Purchase Receipt", "Supplier Quotation",
        "Payment Entry", "Journal Entry", "Material Request", "Stock Entry", "Lead", "Opportunity",
    ]
    out = [d for d in candidates if frappe.db.exists("DocType", d)]
    if frappe.db.exists("DocType", "LumenPDF Template"):
        for d in frappe.get_all("LumenPDF Template", distinct=True, pluck="target_doctype"):
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
            "i": it.get("image") or "",  # product photo (items block showImage preview)
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


def _ensure_config_ready():
    """Config DocTypes must exist before any query touches them. They are created by
    ensure_config (after_install + after_migrate), but a site can still arrive here without them:
    an interrupted install, a restored backup, or an app added to a bench that never migrated.
    Self-heal once instead of throwing a raw TableMissingError at the user."""
    if frappe.db.exists("DocType", "LumenPDF Mapping"):
        return True
    try:
        from lumenpdf.setup.install_config import ensure_config
        ensure_config()
        frappe.clear_cache()
        return frappe.db.exists("DocType", "LumenPDF Mapping")
    except Exception:
        frappe.log_error(title="LumenPDF: config self-heal failed", message=frappe.get_traceback())
        return False


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
        if s == "none":
            continue  # banner opt-out sentinel ("suppress the company banner"), not a path
        if s and not (s.startswith("/files/") or s.startswith("/private/files/")):
            frappe.throw(f"Images must be uploaded files (path starting /files/). Got: {s[:80]}")


def _activate_mapping(target, tmpl_name):
    """Bootstrap only: if the doctype has NO mapping yet, make this the default. Saving a format
    never overwrites an existing default anymore (that was surprising 'last-saved-wins'); the user
    picks the default explicitly via set_default_format / the Formats manager."""
    existing = frappe.get_all(
        "LumenPDF Mapping", filters={"target_doctype": target}, pluck="name", limit=1
    )
    if existing:
        return
    m = frappe.get_doc({"doctype": "LumenPDF Mapping", "target_doctype": target, "template": tmpl_name, "enabled": 1, "priority": 0})
    m.flags.ignore_permissions = True
    m.insert()


def _activate_report_mapping(report_name, tmpl_name, ref_doctype="Report"):
    """Bootstrap: if this report has no mapping yet, point it at the just-saved template so the
    'Branded PDF' button uses it immediately. Never overwrites an existing report mapping."""
    try:
        existing = frappe.get_all(
            "LumenPDF Mapping", filters={"target_kind": "report", "report_name": report_name},
            pluck="name", limit=1,
        )
    except Exception:
        existing = None  # old install: target_kind/report_name columns not migrated yet
    if existing:
        return
    m = frappe.get_doc({"doctype": "LumenPDF Mapping", "target_kind": "report", "report_name": report_name,
                        "target_doctype": ref_doctype, "template": tmpl_name, "enabled": 1, "priority": 0,
                        "replace_report_pdf": 1})
    m.flags.ignore_permissions = True
    m.insert()


# --- internals -------------------------------------------------------------

def _authorize(doctype: str, name: str):
    from lumenpdf import resolver

    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.PermissionError)
    if doctype not in resolver.enabled_doctypes():
        frappe.throw(f"LumenPDF is not enabled for {doctype}.", frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    # Honor the standard 'print' permission too — don't be weaker than the stock Print button.
    if not frappe.has_permission(doctype, "print", doc=doc):
        frappe.throw("You are not permitted to print this document.", frappe.PermissionError)


def _key(job_id: str) -> str:
    return f"lumenpdf:job:{job_id}"


def set_state(job_id: str, state: dict, user: str):
    """Persist job state with the owning user stamped in (used by the worker too)."""
    frappe.cache().set_value(_key(job_id), {**state, "_user": user}, expires_in_sec=900)


def _get_state(job_id: str):
    return frappe.cache().get_value(_key(job_id))
