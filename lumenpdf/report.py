# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L)
# SPDX-License-Identifier: AGPL-3.0-only
# "LumenPDF" and "LumenPDF Studio" are trademarks of Lumen Solutions. See TRADEMARKS.md.
"""Branded PDF for REPORTS (Query / Script / Report Builder), a separate pipeline from documents.

Two entry points, both reusing the same compose engine (repeating header/footer bands, page
numbers, watermark, pagination):

  * Mode A — report_to_pdf(): a drop-in override of frappe.utils.print_format.report_to_pdf (the
    endpoint behind every report's native Print > PDF). When LumenPDF Settings.brand_reports is on,
    the framework-rendered report table is wrapped in the branded header/footer. Zero frontend.
    It only has the pre-rendered HTML (no report name), so it uses the default company branding.

  * Mode B — report_pdf(): a whitelisted endpoint (the "Branded PDF" report-toolbar button) that
    knows the report name + filters, so it re-runs the report and renders a fully styled dynamic
    table through a chosen LumenPDF Template (or a sensible default). This is what the visual
    builder's report mode targets.

Reports have no single "document": data is columns + rows from query_report.run (which enforces
the report's own permissions). We model a run as a lightweight ReportDoc so the doc-oriented block
renderers and compose path work unchanged.
"""
import json
import re

import frappe

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_NUMERIC = {"Int", "Float", "Currency", "Percent"}
REPORT_ROW_CAP = 5000  # hard cap so a huge report can't produce a runaway PDF


class ReportDoc:
    """Minimal doc-like wrapper the block renderers/compose understand. Carries the report payload
    under _bpdf_report; .doctype is a sentinel (not a real DocType) so document-only field lookups
    resolve to empty instead of leaking anything."""

    def __init__(self, data):
        self._d = dict(data or {})
        self.doctype = "LumenPDF Report"
        rep = self._d.get("_bpdf_report") or {}
        self.name = rep.get("name") or "Report"

    def get(self, key, default=None):
        return self._d.get(key, default)

    def get_formatted(self, key):
        v = self._d.get(key)
        return "" if v is None else str(v)


# --- branding / toggles ----------------------------------------------------

def _reports_branding_on():
    try:
        if not frappe.db.exists("DocType", "LumenPDF Settings"):
            return False
        return bool(frappe.db.exists("LumenPDF Settings", {"brand_reports": 1}))
    except Exception:
        return False


def _report_branding(company=None):
    """Branding for a report: the Settings row for `company`, else the default company's, else any.
    Returned as a definition.branding overlay (primary/navy/header_image/footer_image/font)."""
    br = {}
    try:
        if not frappe.db.exists("DocType", "LumenPDF Settings"):
            return br
        name = None
        if company:
            name = frappe.db.get_value("LumenPDF Settings", {"company": company})
        if not name:
            comp = frappe.defaults.get_global_default("company")
            if comp:
                name = frappe.db.get_value("LumenPDF Settings", {"company": comp})
        if not name:
            name = frappe.db.get_value("LumenPDF Settings", {})
        if name:
            s = frappe.get_doc("LumenPDF Settings", name)
            if _HEX.match(s.get("primary_color") or ""):
                br["primary"] = s.primary_color
            if _HEX.match(s.get("secondary_color") or ""):
                br["navy"] = s.secondary_color
            if s.get("header_image"):
                br["header_image"] = s.header_image
            if s.get("footer_image"):
                br["footer_image"] = s.footer_image
            if s.get("font_family"):
                br["font"] = s.font_family
    except Exception:
        pass
    return br


# --- report run + normalization --------------------------------------------

def _align_for(ft):
    return "right" if ft in _NUMERIC else "left"


def _normalize_columns(cols):
    out = []
    for c in cols or []:
        if isinstance(c, dict):
            fn = c.get("fieldname") or c.get("id") or frappe.scrub(c.get("label") or "")
            ft = c.get("fieldtype") or "Data"
            out.append({"fieldname": fn, "label": c.get("label") or fn, "fieldtype": ft,
                        "options": c.get("options"), "align": _align_for(ft), "width": None})
        elif isinstance(c, str) and c.strip():
            parts = c.split(":")
            label = parts[0].strip()
            ft = parts[1].strip() if len(parts) > 1 else "Data"
            opt = None
            if "/" in ft:
                ft, opt = ft.split("/", 1)
            fn = frappe.scrub(label)
            out.append({"fieldname": fn, "label": label, "fieldtype": ft,
                        "options": opt, "align": _align_for(ft), "width": None})
    return out


def _fmt_value(raw, col):
    if raw is None or raw == "":
        return ""
    try:
        s = frappe.format_value(raw, {"fieldtype": col.get("fieldtype"), "options": col.get("options")})
    except Exception:
        s = raw
    try:
        s = frappe.utils.strip_html_tags(str(s)).strip()
    except Exception:
        s = str(s)
    return s


def _format_rows(rawrows, columns, limit=None):
    truncated = False
    rawrows = rawrows or []
    if limit and len(rawrows) > limit:
        rawrows = rawrows[:limit]
        truncated = True
    fieldnames = [c["fieldname"] for c in columns]
    out = []
    for r in rawrows:
        if isinstance(r, dict):
            d = r
        elif isinstance(r, (list, tuple)):
            d = {fieldnames[i]: v for i, v in enumerate(r) if i < len(fieldnames)}
        else:
            continue
        out.append({c["fieldname"]: _fmt_value(d.get(c["fieldname"]), c) for c in columns})
    return out, truncated


def _filter_summary(filters):
    if not isinstance(filters, dict):
        return []
    out = []
    for k, v in filters.items():
        if v in (None, "", []):
            continue
        out.append({"label": frappe.unscrub(k), "value": v if isinstance(v, str) else json.dumps(v, default=str)})
    return out


def _company_from_filters(filters):
    return filters.get("company") if isinstance(filters, dict) else None


def _check_report_perm(report_name):
    if not report_name or not frappe.db.exists("Report", report_name):
        frappe.throw("Unknown report.")
    report = frappe.get_doc("Report", report_name)
    report.check_permission("read")
    ref = report.get("ref_doctype")
    if ref and not frappe.has_permission(ref, "report"):
        raise frappe.PermissionError(f"No report permission on {ref}")
    return report


def _build_report_doc(report_name, filters, limit=REPORT_ROW_CAP):
    from frappe.desk.query_report import run as _run
    res = _run(report_name, filters=filters or {}, ignore_prepared_report=True) or {}
    columns = _normalize_columns(res.get("columns") or [])
    rows, truncated = _format_rows(res.get("result") or [], columns, limit)
    label = frappe.db.get_value("Report", report_name, "report_name") or report_name
    rep = {
        "name": label,
        "columns": columns,
        "rows": rows,
        "filters": _filter_summary(filters),
        "printed_on": frappe.utils.formatdate(frappe.utils.nowdate(), "medium"),
        "native_html": "",
        "truncated": truncated,
    }
    land = len(columns) > 6  # wide reports read better in landscape
    return ReportDoc({"_bpdf_report": rep, "company": _company_from_filters(filters)}), land


def _report_mapping(report_name):
    """Template from the highest-priority enabled report mapping, if any (else None -> default)."""
    try:
        if not frappe.db.exists("DocType", "LumenPDF Mapping"):
            return None
        rows = frappe.get_all("LumenPDF Mapping",
                              filters={"target_kind": "report", "report_name": report_name, "enabled": 1},
                              fields=["template"], order_by="priority asc, creation asc")
        return rows[0]["template"] if rows else None
    except Exception:
        return None  # old install without target_kind/report_name columns


# --- default (template-less) report layout ---------------------------------

def _default_report_def(orientation, branding, body_block, include_meta=False):
    land = str(orientation or "").lower().startswith("land")
    pw, ph = (297.0, 210.0) if land else (210.0, 297.0)
    h_on = bool(branding.get("header_image"))
    f_on = bool(branding.get("footer_image"))
    hh = 26.0 if h_on else 0.0
    fh = 16.0 if f_on else 10.0
    blocks = []
    y = (hh + 6) if h_on else 12.0
    if include_meta:
        blocks.append({"type": "report_title", "region": "body",
                       "pos": {"x": 10, "y": y, "w": pw - 20, "h": 14}, "settings": {}, "style": {}})
        y += 14
        blocks.append({"type": "report_filters", "region": "body",
                       "pos": {"x": 10, "y": y, "w": pw - 20, "h": 8}, "settings": {}, "style": {}})
        y += 10
    blocks.append({"type": body_block, "region": "body",
                   "pos": {"x": 10, "y": y, "w": pw - 20, "h": 100}, "settings": {}, "style": {}})
    blocks.append({"type": "pagenum", "region": "footer",
                   "pos": {"x": pw - 70, "y": ph - 12, "w": 60, "h": 7},
                   "settings": {"format": "Page {p} of {n}"}, "style": {"align": "right"}})
    return {
        "layout": "absolute",
        "page": {"size": "A4", "orientation": "landscape" if land else "portrait"},
        "branding": branding,
        "header": {"enabled": h_on, "height": hh, "margin": 4, "repeat": True},
        "footer": {"enabled": True, "height": fh, "margin": 4, "repeat": True},
        "blocks": blocks,
    }


def _lock():
    from lumenpdf.pdf_job import _acquire
    name = "lumenpdf_render_lock_" + (getattr(frappe.local, "site", None) or "site")
    return name, _acquire(name, "report")


# --- Mode A: wrap the native report Print > PDF ----------------------------

@frappe.whitelist()
def report_to_pdf(html, orientation="Landscape"):
    """Drop-in override of frappe.utils.print_format.report_to_pdf. Wraps the framework's report
    HTML in the branded bands when brand_reports is on; falls back to native on anything unexpected
    (so report printing never breaks)."""
    from frappe.utils.print_format import report_to_pdf as native
    try:
        if _reports_branding_on():
            branding = _report_branding()
            rdoc = ReportDoc({"_bpdf_report": {"name": "Report", "columns": [], "rows": [],
                                               "filters": [], "native_html": html}})
            definition = _default_report_def(orientation, branding, "report_native", include_meta=False)
            from lumenpdf.compose import compose_report_pdf
            lock, got = _lock()
            if got:
                try:
                    pdf = compose_report_pdf(rdoc, definition=definition)
                finally:
                    from lumenpdf.pdf_job import _release
                    _release(lock)
                if pdf:
                    frappe.local.response.filename = "report.pdf"
                    frappe.local.response.filecontent = pdf
                    frappe.local.response.type = "pdf"
                    frappe.local.response.display_content_as = "attachment"
                    return
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="LumenPDF report_to_pdf fell back")
    return native(html, orientation)


# --- Mode B: styled report PDF (toolbar button / builder) ------------------

@frappe.whitelist()
def report_pdf(report_name, filters=None, template=None, orientation=None, definition=None, preview=0):
    """Render a report through a LumenPDF Template (or a branded default). Sets the file response.
    `definition` (System-Manager only) renders an UNSAVED builder design — the builder's report
    Preview PDF; `preview=1` merges best-effort default filters so the design can be previewed
    without opening the report first."""
    _check_report_perm(report_name)
    if isinstance(filters, str):
        try:
            filters = json.loads(filters or "{}")
        except Exception:
            filters = {}
    if isinstance(definition, str):
        try:
            definition = json.loads(definition) if definition.strip() else None
        except Exception:
            definition = None
    if isinstance(definition, dict) and "System Manager" not in frappe.get_roles():
        definition = None  # ad-hoc definitions are a builder (System Manager) feature
    preview = str(preview) in ("1", "true", "True")
    if preview:
        merged = _guess_default_filters()
        merged.update(filters or {})
        filters = merged
    # A preview needs to LOOK right, not be complete — 150 rows keeps the render fast (a first
    # landscape render may run two engines back to back; 5000 GL rows made it hang for minutes).
    row_cap = 150 if preview else REPORT_ROW_CAP
    try:
        rdoc, land = _build_report_doc(report_name, filters, limit=row_cap)
    except Exception:
        if not preview:
            raise
        _clear_messages()
        frappe.throw("This report needs its mandatory filters for a preview — open the report in "
                     "ERPNext, set the filters, then use the Branded PDF button.")
    tmpl = None if isinstance(definition, dict) else (template or _report_mapping(report_name))
    if not tmpl and not isinstance(definition, dict):
        branding = _report_branding(_company_from_filters(filters))
        definition = _default_report_def(orientation or ("landscape" if land else "portrait"),
                                          branding, "report_table", include_meta=True)
    from lumenpdf.compose import compose_report_pdf
    lock, got = _lock()
    if not got:
        frappe.throw("The PDF renderer is busy. Please try again in a moment.")
    try:
        pdf = compose_report_pdf(rdoc, template=tmpl, definition=definition)
    finally:
        from lumenpdf.pdf_job import _release
        _release(lock)
    if not pdf:
        frappe.throw("Could not render the report PDF.")
    safe = re.sub(r"[^\w\-.]", "-", str(report_name)) or "report"
    frappe.local.response.filename = f"{safe}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"
    frappe.local.response.display_content_as = "attachment"


@frappe.whitelist()
def report_sample(report_name, filters=None, limit=50):
    """Columns + a few formatted rows for the builder's live preview of a report format."""
    _check_report_perm(report_name)
    if isinstance(filters, str):
        try:
            filters = json.loads(filters or "{}")
        except Exception:
            filters = {}
    try:
        limit = max(1, min(200, int(limit)))
    except Exception:
        limit = 50

    def _run(f):
        rdoc, _land = _build_report_doc(report_name, f, limit=limit)
        return rdoc.get("_bpdf_report")

    # 1) the plain run; 2) if that throws or returns no columns (mandatory company/dates on most
    #    financial reports), retry with best-effort defaults just to DISCOVER the columns.
    try:
        rep = _run(filters or {})
        if rep.get("columns"):
            return rep
    except Exception:
        _clear_messages()
    try:
        merged = _guess_default_filters()
        merged.update(filters or {})
        rep = _run(merged)
        if rep.get("columns"):
            rep["note"] = "Columns loaded with default filters — the real PDF uses the filters you run the report with."
            return rep
    except Exception:
        pass
    _clear_messages()
    label = frappe.db.get_value("Report", report_name, "report_name") or report_name
    return {"name": label, "columns": [], "rows": [], "filters": _filter_summary(filters),
            "printed_on": frappe.utils.formatdate(frappe.utils.nowdate(), "medium"),
            "native_html": "", "truncated": False,
            "note": "This report needs its own filters to list columns — add columns by fieldname below, "
                    "or leave empty to print every column when the report is run."}


def _clear_messages():
    """Swallow a report's own queued 'X is mandatory' popup (the builder preview is optional)."""
    try:
        frappe.clear_messages()
    except Exception:
        pass
    try:
        frappe.local.message_log = []
    except Exception:
        pass


def _guess_default_filters():
    """Best-effort defaults so a column-discovery run of a standard financial report succeeds
    (company + a 1-year date window + current fiscal year). Only used for the builder preview;
    the real Branded PDF always uses the user's actual report filters."""
    f = {}
    try:
        comp = frappe.defaults.get_user_default("company") or frappe.defaults.get_global_default("company")
        if comp:
            f["company"] = comp
    except Exception:
        pass
    try:
        today = frappe.utils.nowdate()
        start = frappe.utils.add_years(today, -1)
        f["from_date"] = f["period_start_date"] = start
        f["to_date"] = f["period_end_date"] = today
    except Exception:
        pass
    try:
        fy = frappe.defaults.get_user_default("fiscal_year") or frappe.db.get_value(
            "Fiscal Year", {"disabled": 0}, "name", order_by="year_start_date desc")
        if fy:
            f["fiscal_year"] = fy
    except Exception:
        pass
    return f
