"""Resolve a document -> branded HTML.

Phase 1: a static DocType->template map + default branding (BSTC).
Phase 2: resolve template via `BrandPDF Mapping` and branding via `BrandPDF Settings`
(by doc.company). The function signature stays the same so the upgrade is internal.
"""
import frappe

from brandpdf import assets

# Phase 1 map. Paths are relative to the brandpdf package dir (apps/brandpdf/brandpdf/).
TEMPLATE_MAP = {
    "Quotation": "templates/brandpdf/quotation_bstc.html",
}

# Phase 1 branding defaults (Phase 2 reads BrandPDF Settings by company, with this as fallback).
DEFAULT_BRANDING = {
    "primary": "#1C75BC",
    "navy": "#1A1E2A",
    "header_image": "/files/2Header.png",
    "footer_image": "/files/2Footer.png",
    "rtl": True,
    "currency": "BHD",
}


def render_html(doc, template: str = None) -> str:
    relpath = template or TEMPLATE_MAP.get(doc.doctype)
    if not relpath:
        frappe.throw(f"No BrandPDF template configured for {doc.doctype}")
    src = _read_template(relpath)
    html = frappe.render_template(src, {"doc": doc, "branding": get_branding(doc)})
    return assets.inline_images(html)


def get_branding(doc) -> dict:
    # Phase 2 hook: look up BrandPDF Settings for doc.company here; fall back to defaults.
    return dict(DEFAULT_BRANDING)


def _read_template(relpath: str) -> str:
    full = frappe.get_app_path("brandpdf", *relpath.split("/"))
    with open(full, encoding="utf-8") as fh:
        return fh.read()
