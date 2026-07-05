"""Resolve a document -> branded HTML.

Branding + template are resolved via `lumenpdf.resolver`. A template can be:
  - a Jinja file (the shipped quotation), or a DB Jinja body, or
  - a BLOCK format (source_type="blocks") assembled by `lumenpdf.blocks` — the no-code maker.
Falls back to Phase-1 defaults when the config DocTypes don't exist yet.
"""
import os

import frappe
from frappe.utils.html_utils import sanitize_html

from lumenpdf import assets
from lumenpdf.defaults import DEFAULT_BRANDING, TEMPLATE_MAP  # noqa: F401 (re-export)


def render_html(doc, kind=None, value=None) -> str:
    from lumenpdf import resolver  # lazy import: resolver imports defaults, not this module

    branding = resolver.resolve_branding(doc)
    terms_raw = doc.get("terms")
    terms_html = sanitize_html(terms_raw) if terms_raw else ""

    if kind is None:  # caller may pass an explicit chosen template (kind, value); else resolve
        kind, value = resolver.resolve_template(doc)
    allowed = {branding.get("header_image"), branding.get("footer_image")}
    if kind == "blocks":
        from lumenpdf import blocks as blocks_mod
        tmpl = frappe.get_doc("LumenPDF Template", value)
        definition = tmpl.get("definition")
        if definition:
            # The visual builder's saved design — render it exactly as previewed.
            html = blocks_mod.render_definition(doc, definition, terms_html)
            allowed |= blocks_mod.collect_image_srcs(definition)
        else:
            html = blocks_mod.render_blocks(doc, branding, tmpl.get("blocks"), terms_html)
    else:
        # A "body" template is raw Jinja authored ONLY by System Manager (trusted, review #1).
        src = _read_template(value) if kind == "file" else value
        html = frappe.render_template(src, {"doc": doc, "branding": branding, "terms_html": terms_html})

    html = assets.inline_images(html, allowed={a for a in allowed if a})
    return assets.neutralize_remote(html)  # block remaining server-side fetches (SSRF defense)


def _read_template(relpath: str) -> str:
    base = os.path.realpath(frappe.get_app_path("lumenpdf", "templates"))
    full = os.path.realpath(frappe.get_app_path("lumenpdf", *relpath.split("/")))
    if not (full == base or full.startswith(base + os.sep)):
        frappe.throw("Invalid LumenPDF template path.")
    with open(full, encoding="utf-8") as fh:
        return fh.read()
