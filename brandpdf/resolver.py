"""Phase-2 resolution with graceful Phase-1 fallback.

Every lookup is wrapped so the app works whether or not the config DocTypes exist yet:
- enabled_doctypes(): target doctypes of enabled mappings (else ["Quotation"]).
- resolve_branding(doc): BrandPDF Settings by doc.company (else DEFAULT_BRANDING).
- resolve_template(doc): first enabled mapping whose conditions all match (else TEMPLATE_MAP).
Condition matching is a structured fieldname/operator/value matcher — never eval (PLAN H8).
"""
import frappe

from brandpdf.render_html import DEFAULT_BRANDING, TEMPLATE_MAP


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
                if s.get("primary_color"):
                    branding["primary"] = s.primary_color
                if s.get("secondary_color"):
                    branding["navy"] = s.secondary_color
                if s.get("header_image"):
                    branding["header_image"] = s.header_image
                if s.get("footer_image"):
                    branding["footer_image"] = s.footer_image
                branding["rtl"] = bool(s.get("rtl"))
    except Exception:
        frappe.log_error(title="BrandPDF branding resolve failed")
    return branding


def resolve_template(doc):
    """Return (kind, value): ("file", app_relpath) or ("body", html_string)."""
    try:
        if frappe.db.exists("DocType", "BrandPDF Mapping"):
            mappings = frappe.get_all(
                "BrandPDF Mapping",
                filters={"enabled": 1, "target_doctype": doc.doctype},
                fields=["name", "template"],
                order_by="modified desc",
            )
            for m in mappings:
                if _conditions_match(doc, m["name"]):
                    t = frappe.get_doc("BrandPDF Template", m["template"])
                    if t.get("source_type") == "jinja_file" and t.get("jinja_path"):
                        return ("file", t.jinja_path)
                    return ("body", t.get("body") or "")
    except Exception:
        frappe.log_error(title="BrandPDF template resolve failed")

    relpath = TEMPLATE_MAP.get(doc.doctype)
    if not relpath:
        frappe.throw(f"No BrandPDF template configured for {doc.doctype}")
    return ("file", relpath)


def protect_standard_template(doc, method=None):
    """doc_events hook: standard templates are read-only (duplicate to edit)."""
    if doc.get("is_standard") and not doc.is_new():
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
    if op == "=":
        return a == e
    if op == "!=":
        return a != e
    if op == "like":
        return e.replace("%", "").lower() in a.lower()
    if op == "in":
        return a in [x.strip() for x in e.split(",")]
    try:
        af, ef = float(a), float(e)
    except (TypeError, ValueError):
        return False
    return {">": af > ef, "<": af < ef, ">=": af >= ef, "<=": af <= ef}.get(op, False)
