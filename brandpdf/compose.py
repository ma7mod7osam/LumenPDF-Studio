"""Final PDF composition.

For an absolute-layout format with a repeating header/footer band, render the body (which can
flow onto multiple pages, kept clear of the bands via @page margins), then overlay the band onto
every page with real page numbers using pypdf. Works on any engine (incl. frappe_chrome) — no
external service. Falls back to a normal single-pass render otherwise.
"""
import io
import json

import frappe
from frappe.utils.html_utils import sanitize_html

from brandpdf import assets, blocks as B, resolver
from brandpdf.render.base import default_options, get_renderer
from brandpdf.render_html import render_html

PAGE_H = 297.0


def compose_pdf(doc) -> bytes:
    """Entry point used by the render job. Returns final PDF bytes."""
    renderer = get_renderer()
    try:
        kind, value = resolver.resolve_template(doc)
        if kind == "blocks":
            tmpl = frappe.get_doc("BrandPDF Template", value)
            definition = tmpl.get("definition")
            if isinstance(definition, str):
                definition = json.loads(definition)
            if isinstance(definition, dict) and definition.get("layout") == "absolute" and _has_repeat(definition):
                out = _compose_running(doc, definition, renderer)
                if out:
                    return out
    except Exception:
        frappe.log_error(
            title="BrandPDF running header/footer failed; single-pass fallback",
            message=frappe.get_traceback(),
        )
    return renderer.render(render_html(doc), default_options())


def _has_repeat(d):
    h = d.get("header") or {}
    f = d.get("footer") or {}
    return bool((h.get("enabled") and h.get("repeat")) or (f.get("enabled") and f.get("repeat")))


def _finish(html, allowed, renderer):
    html = assets.inline_images(html, allowed=allowed)
    html = assets.neutralize_remote(html)
    return renderer.render(html, default_options())


def _compose_running(doc, definition, renderer):
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        from PyPDF2 import PdfReader, PdfWriter  # older benches

    branding = B._branding_from_def(definition, doc)
    terms_raw = doc.get("terms")
    terms_html = sanitize_html(terms_raw) if terms_raw else ""

    h = definition.get("header") or {}
    f = definition.get("footer") or {}
    hh = float(B._num(h.get("height"), 0) or 0) if (h.get("enabled") and h.get("repeat")) else 0.0
    fh = float(B._num(f.get("height"), 0) or 0) if (f.get("enabled") and f.get("repeat")) else 0.0
    hh = max(0.0, min(hh, PAGE_H))
    fh = max(0.0, min(fh, PAGE_H))
    if hh + fh > PAGE_H - 50:  # bands too tall -> not enough body; let caller single-pass
        return None

    allowed = {branding.get("header_image"), branding.get("footer_image")}
    allowed |= B.collect_image_srcs(definition)  # so builder image elements aren't stripped
    allowed = {a for a in allowed if a}

    body, band = [], []
    for bl in definition.get("blocks") or []:
        if not isinstance(bl, dict):
            continue
        y = B._num((bl.get("pos") or {}).get("y"), 0)
        if hh and y < hh:
            band.append(bl)
        elif fh and y >= PAGE_H - fh:
            band.append(bl)
        else:
            body.append(bl)

    if not band:
        return None  # nothing to repeat -> caller does the normal single pass

    # 1) Body: may span multiple pages; @page top/bottom margins keep it clear of the bands.
    body_html = B._absolute_page_html(
        doc, branding, body, {"terms_html": terms_html}, grow=True, top_mm=hh, bottom_mm=fh, y_shift=hh
    )
    reader = PdfReader(io.BytesIO(_finish(body_html, allowed, renderer)))
    n = len(reader.pages)

    # 2) Overlay the band onto every page. Re-render per page only if it has a page number.
    has_pagenum = any(isinstance(b, dict) and b.get("type") == "pagenum" for b in band)
    writer = PdfWriter()
    overlay = None
    for i in range(n):
        if has_pagenum or overlay is None:
            ov_html = B._absolute_page_html(
                doc, branding, band, {"terms_html": terms_html, "page": i + 1, "total": n}, grow=False
            )
            overlay = PdfReader(io.BytesIO(_finish(ov_html, allowed, renderer)))
        page = reader.pages[i]
        try:
            page.merge_page(overlay.pages[0])
        except AttributeError:
            page.mergePage(overlay.pages[0])  # PyPDF2 naming
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
