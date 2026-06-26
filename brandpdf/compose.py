"""Final PDF composition.

For an absolute-layout (free-canvas) format: the BODY sections flow in document order (so a
variable-length items table never overlaps the totals/terms below it and paginates cleanly),
while the HEADER/FOOTER bands are positioned and overlaid onto each page (repeating, with real
page numbers) using pypdf. Works on any engine (incl. frappe_chrome) — no external service.
Falls back to a normal single-pass render on any error or for non-blocks formats.
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
            if isinstance(definition, dict) and definition.get("layout") == "absolute":
                out = _compose(doc, definition, renderer)
                if out:
                    return out
    except Exception:
        frappe.log_error(title="BrandPDF compose failed; single-pass fallback", message=frappe.get_traceback())
    return renderer.render(render_html(doc), default_options())


def _finish(html, allowed, renderer):
    html = assets.inline_images(html, allowed=allowed)
    html = assets.neutralize_remote(html)
    return renderer.render(html, default_options())


def _derive_region(bl, hh, fh):
    """Back-compat for definitions without an explicit region: derive from the block's Y."""
    y = B._num((bl.get("pos") or {}).get("y"), 0)
    if hh and y < hh:
        return "header"
    if fh and y >= PAGE_H - fh:
        return "footer"
    return "body"


def _compose(doc, definition, renderer):
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        from PyPDF2 import PdfReader, PdfWriter  # older benches

    branding = B._branding_from_def(definition, doc)
    terms_raw = doc.get("terms")
    terms_html = sanitize_html(terms_raw) if terms_raw else ""

    h = definition.get("header") or {}
    f = definition.get("footer") or {}
    h_on = bool(h.get("enabled"))
    f_on = bool(f.get("enabled"))
    hh = max(0.0, min(float(B._num(h.get("height"), 0) or 0), PAGE_H)) if h_on else 0.0
    fh = max(0.0, min(float(B._num(f.get("height"), 0) or 0), PAGE_H)) if f_on else 0.0
    if hh + fh > PAGE_H - 50:  # bands too tall -> let caller single-pass
        return None

    allowed = {branding.get("header_image"), branding.get("footer_image")}
    allowed |= B.collect_image_srcs(definition)
    allowed = {a for a in allowed if a}

    head, body, foot = [], [], []
    for bl in definition.get("blocks") or []:
        if not isinstance(bl, dict):
            continue
        region = bl.get("region") or _derive_region(bl, hh, fh)
        if region == "header" and h_on:
            head.append(bl)
        elif region == "footer" and f_on:
            foot.append(bl)
        else:
            body.append(bl)
    body.sort(key=lambda b: B._num((b.get("pos") or {}).get("y"), 0))  # flow in vertical order

    # 1) Body in flow (may span multiple pages), kept clear of the bands via @page margins.
    body_pdf = _finish(
        B._flow_body_html(doc, branding, body, {"terms_html": terms_html}, top_mm=hh, bottom_mm=fh),
        allowed, renderer,
    )
    reader = PdfReader(io.BytesIO(body_pdf))
    n = len(reader.pages) or 1
    if not head and not foot:
        return body_pdf  # body has no bands -> done

    # 2) Overlay the bands onto each page. Repeat bands appear on all pages; non-repeat header on
    #    page 1, non-repeat footer on the last page. Identical overlays are cached.
    h_rep, f_rep = bool(h.get("repeat")), bool(f.get("repeat"))
    has_pagenum = any(isinstance(b, dict) and b.get("type") == "pagenum" for b in head + foot)
    writer = PdfWriter()
    cache = {}
    for i in range(n):
        bands = []
        if head and (h_rep or i == 0):
            bands += head
        if foot and (f_rep or i == n - 1):
            bands += foot
        page = reader.pages[i]
        if bands:
            key = (i == 0, i == n - 1, (i + 1) if has_pagenum else 0)
            if key not in cache:
                ov = B._absolute_page_html(
                    doc, branding, bands, {"terms_html": terms_html, "page": i + 1, "total": n}, grow=False
                )
                cache[key] = PdfReader(io.BytesIO(_finish(ov, allowed, renderer))).pages[0]
            try:
                page.merge_page(cache[key])
            except AttributeError:
                page.mergePage(cache[key])  # PyPDF2 naming
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
