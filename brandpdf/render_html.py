"""Resolve a document -> branded HTML.

Branding + template are resolved via `brandpdf.resolver` (Phase-2 DocTypes when present,
else Phase-1 defaults from `brandpdf.defaults`). Security: file templates are confined to the
app templates dir (B1); only the branding banner images are base64-inlined (allowlist, H4).
"""
import os

import frappe
from frappe.utils.html_utils import sanitize_html

from brandpdf import assets
from brandpdf.defaults import DEFAULT_BRANDING, TEMPLATE_MAP  # noqa: F401 (re-export)


def render_html(doc) -> str:
    from brandpdf import resolver  # lazy import: resolver imports defaults, not this module

    branding = resolver.resolve_branding(doc)
    kind, value = resolver.resolve_template(doc)
    # A "body" template is raw Jinja authored ONLY by System Manager (BrandPDF Template write
    # perm is locked to that role) — body authors are trusted as developers (review #1).
    src = _read_template(value) if kind == "file" else value
    terms_raw = doc.get("terms")
    context = {
        "doc": doc,
        "branding": branding,
        # Sanitize here (Python). frappe.utils.sanitize_html is NOT callable inside the
        # Jinja sandbox, so we pre-render it and the template uses {{ terms_html | safe }}.
        "terms_html": sanitize_html(terms_raw) if terms_raw else "",
    }
    html = frappe.render_template(src, context)
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
