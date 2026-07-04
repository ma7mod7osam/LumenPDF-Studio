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


def compose_pdf(doc, template=None) -> bytes:
    """Entry point used by the render job. `template` (optional) selects a specific BrandPDF
    Template for this doctype; otherwise the mapped/default one is used. Returns PDF bytes."""
    renderer = get_renderer()
    try:
        kind, value, definition = _resolve(doc, template)
        if kind == "blocks" and isinstance(definition, dict) and definition.get("layout") == "absolute":
            out = _compose(doc, definition, renderer)
            if out:
                return out
        if kind:
            return renderer.render(render_html(doc, kind, value), default_options())
    except Exception:
        frappe.log_error(title="BrandPDF compose failed; single-pass fallback", message=frappe.get_traceback())
    return renderer.render(render_html(doc), default_options())


def _resolve(doc, template):
    """Return (kind, value, definition). A valid chosen template (matching this doctype) wins;
    otherwise fall back to the resolver's mapped/default template."""
    if template and frappe.db.exists("BrandPDF Template", template):
        t = frappe.get_doc("BrandPDF Template", template)
        if (t.get("target_doctype") or "") == doc.doctype:
            st = t.get("source_type")
            if st == "blocks":
                d = t.get("definition")
                if isinstance(d, str):
                    d = json.loads(d)
                return ("blocks", t.name, d if isinstance(d, dict) else None)
            if st == "jinja_file" and t.get("jinja_path"):
                return ("file", t.jinja_path, None)
            return ("body", t.get("body") or "", None)
    kind, value = resolver.resolve_template(doc)
    definition = None
    if kind == "blocks":
        t = frappe.get_doc("BrandPDF Template", value)
        d = t.get("definition")
        if isinstance(d, str):
            d = json.loads(d)
        definition = d if isinstance(d, dict) else None
    return (kind, value, definition)


def _margins_honored(renderer):
    """Probe (once a day, cached) whether the active PDF engine honors page margins at all —
    via @page CSS or the explicit options. A 250mm block with 100mm top+bottom margins MUST
    paginate; if the probe comes back as one page, the engine ignores margins and compose
    switches to spacer_mode (thead/tfoot spacer clearance baked into the body HTML)."""
    try:
        cached = frappe.cache().get_value("brandpdf_margins_honored")
        if cached is not None:
            return str(cached) == "1"
    except Exception:
        pass
    honored = True
    try:
        probe = ('<!DOCTYPE html><html><head><style>@page{size:A4;margin:100mm 0mm;}'
                 'html,body{margin:0;padding:0;}</style>'
                 '<style>.print-format{margin-top:100mm;margin-bottom:100mm;margin-left:0mm;margin-right:0mm;}</style>'
                 '</head><body><div style="height:250mm;width:100mm;">probe</div></body></html>')
        opts = default_options()
        opts["margin"] = {"top": "100mm", "bottom": "100mm", "left": "0mm", "right": "0mm"}
        pdf = renderer.render(probe, opts)
        honored = len(PdfReader(io.BytesIO(pdf)).pages) >= 2
    except Exception:
        honored = True  # can't probe -> keep the standard path, but leave a trace to diagnose
        try:
            frappe.log_error(message=frappe.get_traceback(), title="BrandPDF margin probe failed")
        except Exception:
            pass
    try:
        frappe.cache().set_value("brandpdf_margins_honored", "1" if honored else "0", expires_in_sec=86400)
    except Exception:
        pass
    return honored


def clear_probe_cache():
    """after_migrate: a new deploy may change engine behavior — force a fresh margin probe."""
    try:
        frappe.cache().delete_value("brandpdf_margins_honored")
    except Exception:
        pass


def _finish(html, allowed, renderer, margins=None):
    """margins={'top': mm, 'bottom': mm} passes the band clearance as EXPLICIT page margins.
    The @page CSS alone is not enough: wkhtmltopdf ignores @page margins entirely, and Chrome's
    CDP printToPDF applies param margins when CSS gives none — so the body must carry its
    clearance in the renderer options too (engines never stack the two)."""
    html = assets.inline_images(html, allowed=allowed)
    html = assets.neutralize_remote(html)
    options = default_options()
    if margins:
        options["margin"] = {
            "top": f"{B._fmt_num(margins.get('top', 0))}mm",
            "bottom": f"{B._fmt_num(margins.get('bottom', 0))}mm",
            "left": "0mm", "right": "0mm",
        }
    return renderer.render(html, options)


def _watermark_text(doc, wm):
    """Conditional watermark: first matching rule (field/op/value) picks the text — e.g.
    status = Paid -> 'PAID', status = Draft -> 'DRAFT'; falls back to the fixed text."""
    for r in (wm.get("rules") or []) if isinstance(wm.get("rules"), (list, tuple)) else []:
        if not isinstance(r, dict) or not r.get("field") or not (r.get("text") or "").strip():
            continue
        try:
            if resolver._match(doc.get(r.get("field")), r.get("op") or "=", r.get("value")):
                return r["text"].strip()
        except Exception:
            continue
    return (wm.get("text") or "").strip()


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
    hm = max(0.0, float(B._num(h.get("margin"), 0) or 0)) if h_on else 0.0  # clear gap below header
    fm = max(0.0, float(B._num(f.get("margin"), 0) or 0)) if f_on else 0.0  # clear gap above footer
    if hh + fh + hm + fm > PAGE_H - 50:  # bands too tall -> let caller single-pass
        return None

    allowed = {branding.get("header_image"), branding.get("footer_image")}
    allowed |= B.collect_image_srcs(definition)
    allowed = {a for a in allowed if a}

    head, body, foot = [], [], []
    for bl in definition.get("blocks") or []:
        if not isinstance(bl, dict):
            continue
        if not B._visible(doc, bl):
            continue  # conditionally-hidden block: don't let it drive overlay/page-number/short-circuit
        region = bl.get("region") or _derive_region(bl, hh, fh)
        if region == "header" and h_on:
            head.append(bl)
        elif region == "footer" and f_on:
            foot.append(bl)
        else:
            body.append(bl)
    flow_body = [b for b in body if not b.get("float")]
    float_body = [b for b in body if b.get("float")]  # free-positioned elements
    flow_body.sort(key=lambda b: B._num((b.get("pos") or {}).get("y"), 0))  # flow in vertical order

    # Banner is a band background driven by the branding image, sized to the band (not a saved block).
    head = [b for b in head if b.get("type") != "header_banner"]
    foot = [b for b in foot if b.get("type") != "footer_banner"]
    if h_on and branding.get("header_image"):
        head.insert(0, {"type": "header_banner", "settings": {}, "style": {}, "region": "header",
                        "pos": {"x": 0, "y": 0, "w": 210, "h": hh}})
    if f_on and branding.get("footer_image"):
        foot.insert(0, {"type": "footer_banner", "settings": {}, "style": {}, "region": "footer",
                        "pos": {"x": 0, "y": PAGE_H - fh, "w": 210, "h": fh}})

    # 1) Body in flow (+ floating elements), may span multiple pages, kept clear of the bands.
    honored = _margins_honored(renderer)
    body_pdf = _finish(
        B._flow_body_html(doc, branding, flow_body, {"terms_html": terms_html},
                          top_mm=hh + hm, bottom_mm=fh + fm, floats=float_body, spacer_mode=not honored),
        allowed, renderer, margins=({"top": hh + hm, "bottom": fh + fm} if honored else None),
    )
    reader = PdfReader(io.BytesIO(body_pdf))
    n = len(reader.pages) or 1

    # Watermark page (rendered once) is merged BEHIND every page.
    wm = definition.get("watermark")
    wm_bytes = None
    if isinstance(wm, dict):
        wm = dict(wm, text=_watermark_text(doc, wm))  # conditional rules may pick the text per doc
    if isinstance(wm, dict) and wm.get("text"):
        wm_html = B.watermark_page_html(branding, wm)
        if wm_html:
            wm_bytes = _finish(wm_html, allowed, renderer)

    if not head and not foot and not wm_bytes:
        return body_pdf  # nothing to overlay -> plain body

    # 2) Per page: watermark (behind) <- body <- header/footer bands (on top). Repeat bands appear
    #    on all pages; non-repeat header on page 1, non-repeat footer on the last page. Overlays cached.
    h_rep, f_rep = bool(h.get("repeat")), bool(f.get("repeat"))
    has_pagenum = any(isinstance(b, dict) and b.get("type") == "pagenum" for b in head + foot)
    writer = PdfWriter()
    cache = {}
    for i in range(n):
        if wm_bytes:
            page = PdfReader(io.BytesIO(wm_bytes)).pages[0]  # fresh watermark base per page
            try:
                page.merge_page(reader.pages[i])
            except AttributeError:
                page.mergePage(reader.pages[i])
        else:
            page = reader.pages[i]
        bands = []
        if head and (h_rep or i == 0):
            bands += head
        if foot and (f_rep or i == n - 1):
            bands += foot
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
