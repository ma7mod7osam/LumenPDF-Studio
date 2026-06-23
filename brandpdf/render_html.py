"""Resolve a document -> branded HTML.

Phase 1: a static DocType->template map + default branding (BSTC).
Phase 2: resolve template via `BrandPDF Mapping` and branding via `BrandPDF Settings`.

Security (code review B1): the template is chosen SERVER-SIDE from TEMPLATE_MAP only — never
from client input — and `_read_template` confines reads to the app's templates dir.
Only the branding banner images are base64-inlined (allowlist), so document content cannot
cause arbitrary local files to be embedded (H4).
"""
import os

import frappe

from brandpdf import assets

# Paths are relative to the brandpdf package dir (apps/brandpdf/brandpdf/).
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
}


def render_html(doc) -> str:
    relpath = TEMPLATE_MAP.get(doc.doctype)
    if not relpath:
        frappe.throw(f"No BrandPDF template configured for {doc.doctype}")
    src = _read_template(relpath)
    branding = get_branding(doc)
    html = frappe.render_template(src, {"doc": doc, "branding": branding})
    # Only inline the known branding banners — not arbitrary <img> from document content.
    allowed = {branding.get("header_image"), branding.get("footer_image")}
    return assets.inline_images(html, allowed={a for a in allowed if a})


def get_branding(doc) -> dict:
    # Phase 2 hook: look up BrandPDF Settings for doc.company here; fall back to defaults.
    return dict(DEFAULT_BRANDING)


def _read_template(relpath: str) -> str:
    base = os.path.realpath(frappe.get_app_path("brandpdf", "templates"))
    full = os.path.realpath(frappe.get_app_path("brandpdf", *relpath.split("/")))
    if not (full == base or full.startswith(base + os.sep)):
        frappe.throw("Invalid BrandPDF template path.")
    with open(full, encoding="utf-8") as fh:
        return fh.read()
