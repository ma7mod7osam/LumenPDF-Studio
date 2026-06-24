"""Resolve a document -> branded HTML.

Branding + template are resolved via `brandpdf.resolver` (Phase-2 DocTypes when present,
else Phase-1 defaults below). Security: file templates are confined to the app templates dir
(B1); only the branding banner images are base64-inlined (allowlist, H4).
"""
import os

import frappe

from brandpdf import assets

# Phase 1 fallback map. Paths are app-relative (apps/brandpdf/brandpdf/).
TEMPLATE_MAP = {
    "Quotation": "templates/brandpdf/quotation_bstc.html",
}

# Phase 1 fallback branding (resolver overrides per-company via BrandPDF Settings).
DEFAULT_BRANDING = {
    "primary": "#1C75BC",
    "navy": "#1A1E2A",
    "header_image": "/files/2Header.png",
    "footer_image": "/files/2Footer.png",
    "rtl": True,
}


def render_html(doc) -> str:
    from brandpdf import resolver  # lazy import to avoid an import cycle

    branding = resolver.resolve_branding(doc)
    kind, value = resolver.resolve_template(doc)
    src = _read_template(value) if kind == "file" else value
    html = frappe.render_template(src, {"doc": doc, "branding": branding})
    # Only inline the known branding banners — not arbitrary <img> from document content.
    allowed = {branding.get("header_image"), branding.get("footer_image")}
    return assets.inline_images(html, allowed={a for a in allowed if a})


def _read_template(relpath: str) -> str:
    base = os.path.realpath(frappe.get_app_path("brandpdf", "templates"))
    full = os.path.realpath(frappe.get_app_path("brandpdf", *relpath.split("/")))
    if not (full == base or full.startswith(base + os.sep)):
        frappe.throw("Invalid BrandPDF template path.")
    with open(full, encoding="utf-8") as fh:
        return fh.read()
