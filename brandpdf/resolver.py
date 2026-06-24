"""Phase-2 resolution with graceful Phase-1 fallback.

Every lookup is wrapped so the app works whether or not the config DocTypes exist yet.
Condition matching is a structured fieldname/operator/value matcher — never eval (PLAN H8).
"""
import re

import frappe

from brandpdf.defaults import DEFAULT_BRANDING, TEMPLATE_MAP

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def enabled_doctypes():
    try:
        if not frappe.db.exists("DocType", "BrandPDF Mapping"):
            return ["Quotation"]
        dts = frappe.get_all("BrandPDF Mapping", filters={"enabled": 1}, distinct=True, pluck="target_doctype")
        return dts or ["Quotation"]
    except Exception:
        return ["Quotation"]


def resolve_branding(doc):
    branding = dict(DEFAULT_BRANDING)
    try:
        company = doc.get("company")
        if company and frappe.db.exists("DocType", "BrandPDF Settings"):
            name = frappe.db.get_value("BrandPDF Settings", {"company": company})
            if name:
                s = frappe.get_doc("BrandPDF Settings", name)
                # Validate hex so a bad value can't break the rendered CSS (review #8).
                if _HEX.match(s.get("primary_color") or ""):
                    branding["primary"] = s.primary_color
                if _HEX.match(s.get("secondary_color") or ""):
                    branding["navy"] = s.secondary_color
                if s.get("header_image"):
                    branding["header_image"] = s.header_image
                if s.get("footer_image"):
                    branding["footer_image"] = s.footer_image
                branding["rtl"] = bool(s.get("rtl"))
    except Exception:
        frappe.log_error(title="BrandPDF branding resolve failed", message=frappe.get_traceback())
    return branding


def resolve_template(doc):
    """Return (kind, value): ("file", app_relpath) or ("body", html_string)."""
    try:
        if frappe.db.exists("DocType", "BrandPDF Mapping"):
            mappings = frappe.get_all(
                "BrandPDF Mapping",
                filters={"enabled": 1, "target_doctype": doc.doctype},
                fields=["name", "template"],
                order_by="priority asc, creation asc",  # deterministic precedence (review #10)
            )
            for m in mappings:
                if _conditions_match(doc, m["name"]):
                    t = frappe.get_doc("BrandPDF Template", m["template"])
                    if t.get("source_type") == "jinja_file" and t.get("jinja_path"):
                        return ("file", t.jinja_path)
                    return ("body", t.get("body") or "")
    except Exception:
        frappe.log_error(title="BrandPDF template resolve failed", message=frappe.get_traceback())

    relpath = TEMPLATE_MAP.get(doc.doctype)
    if not relpath:
        frappe.throw(f"No BrandPDF template configured for {doc.doctype}")
    return ("file", relpath)


def protect_standard_template(doc, method=None):
    """doc_events hook: standard templates are read-only (duplicate to edit) — but never
    block install/migrate/patch re-syncs, which would abort the migration (review #2)."""
    if doc.get("is_standard") and not doc.is_new():
        if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_patch:
            return
        if not getattr(doc.flags, "brandpdf_allow_standard_edit", False):
            frappe.throw("Standard BrandPDF templates are read-only. Duplicate to edit.")


# --- structured condition matching (no eval) -------------------------------

def _conditions_match(doc, mapping_name):
    rows = frappe.get_all(
        "BrandPDF Mapping Condition",
        filters={"parent": mapping_name},
        fields=["fieldname", "operator", "value"],
        order_by="idx",
    )
    return all(_match(doc.get(r["fieldname"]), r["operator"], r["value"]) for r in rows)


def _match(actual, op, expected):
    a = "" if actual is None else str(actual)
    e = "" if expected is None else str(expected)
    if op in ("=", "!="):
        # numeric-aware equality so 5.0 == "5" (review #5)
        try:
            eq = float(a) == float(e)
        except (TypeError, ValueError):
            eq = a == e
        return eq if op == "=" else (not eq)
    if op == "like":
        needle = e.replace("%", "").strip().lower()
        return bool(needle) and needle in a.lower()  # empty pattern matches nothing, not everything
    if op == "in":
        return a in [x.strip() for x in e.split(",")]
    # numeric comparisons only (review #5)
    try:
        af, ef = float(a), float(e)
    except (TypeError, ValueError):
        return False
    return {">": af > ef, "<": af < ef, ">=": af >= ef, "<=": af <= ef}.get(op, False)
