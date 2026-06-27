"""Block engine — assemble a print format from an ordered list of blocks.

A "format" is just blocks: header_banner, title, customer, items, totals,
payment_schedule, terms, signature, footer_banner, spacer, custom_html.
`render_blocks(doc, branding, rows, terms_html)` turns that list into the same clean,
full-bleed HTML the hand-written template produces — so non-coders compose formats by
adding/reordering block rows (Stage 1: a form; Stage 2: drag-and-drop UI on top).

Each block renderer takes (doc, branding, row, ctx) and returns an HTML fragment. `row`
is the block config (block_type, label, content). Banners render full-width; everything
else sits inside a padded content area.

The visual builder produces a DEFINITION (branding + an ordered list of {type, settings,
style}); `render_definition()` turns that into the SAME HTML the builder previews, so the
PDF matches the builder exactly. Generic elements (heading/text/field/image/divider/box/
table) are mirrored from the builder's JS renderers.
"""
import json
import re

import frappe

CONTENT_BLOCKS_ORDER = [
    "header_banner", "title", "customer", "items", "totals",
    "payment_schedule", "terms", "signature", "footer_banner",
]

BANNER_BLOCKS = {"header_banner", "footer_banner"}


def base_css(b):
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    font = b.get("font") or "Montserrat"
    return f"""<style>
  @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&family=Montserrat:wght@300;400;500;600;700;800&display=swap');
  @page {{ size: A4; margin: 0; }}
  html, body {{ margin:0 !important; padding:0 !important; }}
  img {{ max-width:100%; }}
  .bs-banner {{ width:100%; display:block; }}
  .bs-content {{ font-family:'{font}','Segoe UI',Arial,sans-serif; color:{navy}; font-size:8.5pt; padding:6mm 14mm; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  table.bs-head {{ width:100%; border-collapse:collapse; margin-bottom:8mm; }}
  table.bs-head td {{ border:0; vertical-align:top; padding:0; }}
  .bs-title {{ font-size:23pt; font-weight:800; letter-spacing:1px; line-height:1; color:{navy}; }}
  .bs-title-ar {{ font-family:'Cairo','Tajawal',Tahoma,sans-serif; font-size:12pt; font-weight:600; color:{primary}; direction:rtl; margin-top:6px; }}
  table.bs-meta {{ display:inline-block; text-align:left; border:1px solid #cfe5f6; border-collapse:collapse; font-size:8pt; }}
  table.bs-meta td {{ border:1px solid #cfe5f6; padding:3px 7px; }}
  table.bs-meta td.k {{ font-weight:600; }}
  .bs-billto {{ margin-bottom:6mm; }}
  .bs-billto .lbl {{ font-size:7pt; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; color:{primary}; margin-bottom:3px; }}
  .bs-billto .name {{ font-size:10pt; font-weight:700; }}
  .bs-billto .addr {{ color:#6b6b6e; font-size:8pt; line-height:1.5; }}
  table.bs-items {{ width:100%; border-collapse:collapse; margin-bottom:6mm; table-layout:fixed; }}
  table.bs-items th, table.bs-items td {{ word-wrap:break-word; }}
  table.bs-items thead th {{ background-color:{primary} !important; color:#fff !important; font-weight:600; font-size:7.5pt; padding:6px 8px; text-align:left; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  table.bs-items thead th.num {{ text-align:right; }}
  table.bs-items tbody td {{ padding:6px 8px; border-bottom:1px solid #cfe5f6; vertical-align:top; font-weight:normal; }}
  table.bs-items td.num {{ text-align:right; white-space:nowrap; }}
  table.bs-items tbody tr {{ break-inside:avoid; }}
  table.bs-items tbody tr:nth-child(even) td {{ background-color:#eef6fc !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  table.bs-items.nozebra tbody tr:nth-child(even) td {{ background-color:transparent !important; }}
  table.bs-items tbody td *:not(.it-name):not(.it-desc) {{ font-weight:normal !important; background:transparent !important; border:0 !important; color:{navy} !important; }}
  table.bs-items .it-name {{ font-weight:600 !important; }}
  table.bs-items .it-desc {{ color:#6b6b6e !important; font-size:7pt; line-height:1.4; }}
  table.bs-tot {{ width:100%; border-collapse:collapse; font-size:8pt; }}
  table.bs-tot td {{ padding:4px 8px; border:0; }}
  table.bs-tot td.lbl {{ color:#6b6b6e; text-align:right; }}
  table.bs-tot td.val {{ text-align:right; white-space:nowrap; font-weight:600; }}
  table.bs-tot tr.grand {{ break-inside:avoid; }}
  .bs-sec-lbl {{ font-size:7pt; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; color:{primary}; margin-bottom:3px; }}
  .bs-sign-box {{ display:inline-block; min-width:60mm; text-align:center; border-top:1.5px solid {navy}; padding-top:4px; font-size:8.5pt; font-weight:600; margin-top:14mm; }}
</style>"""


# --- individual block renderers -------------------------------------------

def _b_header_banner(doc, b, row, ctx):
    return f'<img class="bs-banner" src="{frappe.utils.escape_html(b.get("header_image") or "")}">'


def _b_footer_banner(doc, b, row, ctx):
    return f'<img class="bs-banner" src="{frappe.utils.escape_html(b.get("footer_image") or "")}">'


def _b_title(doc, b, row, ctx):
    title = (row.get("label") or "QUOTATION")
    meta = [
        ("Quotation No", doc.name),
        ("Date", doc.get_formatted("transaction_date")),
    ]
    if doc.get("valid_till"):
        meta.append(("Valid Till", doc.get_formatted("valid_till")))
    rows = "".join(f'<tr><td class="k">{frappe.utils.escape_html(k)}</td><td><bdi>{frappe.utils.escape_html(v)}</bdi></td></tr>' for k, v in meta)
    return (
        '<table class="bs-head"><tr>'
        f'<td style="text-align:left;"><div class="bs-title">{frappe.utils.escape_html(title)}</div>'
        '<div class="bs-title-ar">عرض سعر</div></td>'
        f'<td style="text-align:right;"><table class="bs-meta">{rows}</table></td>'
        '</tr></table>'
    )


def _b_customer(doc, b, row, ctx):
    name = doc.get("customer_name") or doc.get("party_name") or ""
    out = ['<div class="bs-billto"><div class="lbl">Quotation To</div>']
    out.append(f'<div class="name">{frappe.utils.escape_html(name)}</div>')
    addr = doc.get("address_display")
    if addr:
        # address_display is system HTML; sanitize (keeps <br>, strips scripts/handlers).
        from frappe.utils.html_utils import sanitize_html
        out.append(f'<div class="addr">{sanitize_html(addr)}</div>')
    contact = doc.get("contact_display")
    if contact:
        out.append(f'<div class="addr">Attn: {frappe.utils.escape_html(contact)}</div>')
    out.append('</div>')
    return "".join(out)


def _b_items(doc, b, row, ctx):
    head = (
        '<table class="bs-items"><thead><tr>'
        '<th style="width:6%">#</th><th style="width:40%">Item &amp; Description</th>'
        '<th class="num" style="width:12%">Qty</th><th class="num" style="width:20%">Rate</th>'
        '<th class="num" style="width:22%">Amount</th></tr></thead><tbody>'
    )
    body = []
    for i, it in enumerate(doc.get("items") or [], start=1):
        name_txt = frappe.utils.strip_html_tags(it.item_name or "").strip()
        nm = frappe.utils.escape_html(name_txt)
        desc = (it.get("description") or "")
        desc_txt = frappe.utils.strip_html_tags(desc).strip() if desc else ""
        desc_html = ""
        if desc_txt and desc_txt != name_txt:  # strip+trim BOTH sides (match the reference template)
            desc_html = f'<div class="it-desc">{frappe.utils.escape_html(desc_txt)}</div>'
        body.append(
            f'<tr><td class="num">{i}</td>'
            f'<td><div class="it-name">{nm}</div>{desc_html}</td>'
            f'<td class="num"><bdi>{it.get_formatted("qty")} {frappe.utils.escape_html(it.get("uom") or "")}</bdi></td>'
            f'<td class="num"><bdi>{it.get_formatted("rate")}</bdi></td>'
            f'<td class="num"><bdi>{it.get_formatted("amount")}</bdi></td></tr>'
        )
    return head + "".join(body) + "</tbody></table>"


def _b_totals(doc, b, row, ctx):
    primary = b.get("primary", "#1C75BC")
    lines = [f'<tr><td class="lbl">Subtotal</td><td class="val"><bdi>{doc.get_formatted("total")}</bdi></td></tr>']
    if doc.get("discount_amount"):
        lines.append(f'<tr><td class="lbl">Discount</td><td class="val"><bdi>- {doc.get_formatted("discount_amount")}</bdi></td></tr>')
    for tax in (doc.get("taxes") or []):
        if tax.tax_amount:
            d = frappe.utils.escape_html(frappe.utils.strip_html_tags(tax.description or ""))
            lines.append(f'<tr><td class="lbl">{d}</td><td class="val"><bdi>{tax.get_formatted("tax_amount")}</bdi></td></tr>')
    grand = (
        f'<tr class="grand">'
        f'<td style="background-color:{primary} !important;color:#fff !important;font-weight:700;font-size:10pt;text-align:right;padding:6px 8px;-webkit-print-color-adjust:exact;">Grand Total</td>'
        f'<td style="background-color:{primary} !important;color:#fff !important;font-weight:700;font-size:10pt;text-align:right;white-space:nowrap;padding:6px 8px;-webkit-print-color-adjust:exact;"><bdi>{doc.get_formatted("grand_total")}</bdi></td></tr>'
    )
    return (
        '<table style="width:100%;border-collapse:collapse;"><tr><td style="border:0;"></td>'
        '<td style="border:0;width:82mm;"><table class="bs-tot">' + "".join(lines) + grand + '</table></td></tr></table>'
    )


def _b_payment_schedule(doc, b, row, ctx):
    if not doc.get("payment_schedule"):
        return ""
    head = (
        '<div style="margin-top:6mm;"><div class="bs-sec-lbl">Payment Schedule</div>'
        '<table class="bs-items"><thead><tr><th style="width:6%">#</th><th style="width:46%">Payment Term</th>'
        '<th class="num" style="width:18%">Due Date</th><th class="num" style="width:12%">Portion %</th>'
        '<th class="num" style="width:18%">Amount</th></tr></thead><tbody>'
    )
    body = []
    for i, ps in enumerate(doc.payment_schedule, start=1):
        term = frappe.utils.escape_html(ps.get("payment_term") or ps.get("description") or "")
        body.append(
            f'<tr><td class="num">{i}</td><td><div class="it-name">{term}</div></td>'
            f'<td class="num"><bdi>{ps.get_formatted("due_date")}</bdi></td>'
            f'<td class="num"><bdi>{ps.get_formatted("invoice_portion")}</bdi></td>'
            f'<td class="num"><bdi>{ps.get_formatted("payment_amount")}</bdi></td></tr>'
        )
    return head + "".join(body) + "</tbody></table></div>"


def _b_terms(doc, b, row, ctx):
    terms_html = ctx.get("terms_html") or ""
    if not terms_html:
        return ""
    return (
        '<div style="margin-top:7mm;font-size:7.5pt;color:#6b6b6e;line-height:1.5;">'
        '<div class="bs-sec-lbl">Terms &amp; Conditions</div>' + terms_html + '</div>'
    )


def _b_signature(doc, b, row, ctx):
    label = frappe.utils.escape_html(row.get("label") or "Authorized Signature")
    return (
        '<table style="width:100%;border-collapse:collapse;"><tr><td style="border:0;"></td>'
        f'<td style="border:0;width:60mm;text-align:center;"><div class="bs-sign-box">{label}</div></td></tr></table>'
    )


def _b_spacer(doc, b, row, ctx):
    return '<div style="height:8mm;"></div>'


def _b_custom_html(doc, b, row, ctx):
    from frappe.utils.html_utils import sanitize_html
    raw = row.get("content") or ""
    return sanitize_html(raw) if raw else ""


BLOCKS = {
    "header_banner": _b_header_banner,
    "footer_banner": _b_footer_banner,
    "title": _b_title,
    "customer": _b_customer,
    "items": _b_items,
    "totals": _b_totals,
    "payment_schedule": _b_payment_schedule,
    "terms": _b_terms,
    "signature": _b_signature,
    "spacer": _b_spacer,
    "custom_html": _b_custom_html,
}


def default_blocks():
    """A sensible starting format (mirrors the hand-written quotation)."""
    order = ["header_banner", "title", "customer", "items", "totals", "payment_schedule", "terms", "footer_banner"]
    return [{"block_type": bt} for bt in order]


def render_blocks(doc, branding, rows, terms_html=""):
    rows = rows or default_blocks()
    ctx = {"terms_html": terms_html}
    parts = [base_css(branding)]
    content_open = [False]

    def close_content():
        if content_open[0]:
            parts.append("</div>")
            content_open[0] = False

    def open_content():
        if not content_open[0]:
            parts.append('<div class="bs-content">')
            content_open[0] = True

    for r in rows:
        bt = (r.get("block_type") if hasattr(r, "get") else None) or ""
        if bt in BANNER_BLOCKS:
            close_content()
            parts.append(BLOCKS[bt](doc, branding, r, ctx))
        elif bt in BLOCKS:
            open_content()
            parts.append(BLOCKS[bt](doc, branding, r, ctx))
        # unknown block types are skipped silently
    close_content()
    return "".join(parts)


# ===========================================================================
# DEFINITION model — what the visual builder saves/loads. Mirrors builder JS.
# ===========================================================================

_HEX = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
_ALIGN = {"left", "center", "right", "justify"}
_BORDER_STYLE = {"solid", "dashed", "dotted", "double", "none"}
_WEIGHT = {"400", "500", "600", "700", "800", "normal", "bold"}
_WIDTH = re.compile(r"^\d+(\.\d+)?(mm|%|px|cm)$")
_FONTS = {"Montserrat", "Cairo", "Arial", "Tahoma"}  # allow-list (font is injected into <style>)


def _esc(s):
    return frappe.utils.escape_html("" if s is None else str(s))


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_num(v):
    """Render a number without a trailing .0 (so 1.0 -> '1'). Tolerates numeric strings."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f == int(f):
        return str(int(f))
    return str(f)


def _hexok(v):
    return isinstance(v, str) and bool(_HEX.match(v.strip()))


def _field_value(doc, field):
    if not field:
        return ""
    try:
        v = doc.get_formatted(field)
    except Exception:
        v = doc.get(field)
    return "" if v is None else str(v)


def _visible(doc, bl):
    """Conditional visibility: a block with a `cond` {field, op, value} renders only when the
    document's field satisfies it. No cond -> always visible."""
    c = bl.get("cond") or {}
    f = c.get("field")
    if not f:
        return True
    try:
        from brandpdf.resolver import _match
        return _match(doc.get(f), c.get("op") or "=", c.get("value"))
    except Exception:
        return True


def _style_css(style, type_=None, absolute=False):
    """Validate the builder's style object into a safe inline CSS string (mirror of the
    builder's styleCss). Colors are hex-only; sizes/spacings numeric; enums allow-listed —
    so a saved style can never inject arbitrary CSS. In absolute (free-canvas) layout, margins
    and width are skipped (position/size come from the block's pos)."""
    if not isinstance(style, dict):
        style = {}
    p = []
    a = style.get("align")
    if a in _ALIGN:
        p.append("text-align:" + a)
    sz = _num(style.get("size"))
    if sz is not None:
        p.append(f"font-size:{_fmt_num(sz)}pt")
    w = str(style.get("weight") or "")
    if w in _WEIGHT:
        p.append("font-weight:" + w)
    if style.get("italic"):
        p.append("font-style:italic")
    if _hexok(style.get("color")):
        p.append("color:" + style["color"].strip())
    if _hexok(style.get("bg")):
        p.append("background:" + style["bg"].strip())
    spacing = (("pad", "padding"),) if absolute else (("mt", "margin-top"), ("mb", "margin-bottom"), ("pad", "padding"))
    for key, css in spacing:
        v = _num(style.get(key))
        if v is not None:
            p.append(f"{css}:{_fmt_num(v)}mm")
    if not absolute:
        width = style.get("width")
        if isinstance(width, str) and _WIDTH.match(width.strip()):
            p.append("width:" + width.strip())
    b = style.get("border") or {}
    if isinstance(b, dict) and b.get("on"):
        bw = _num(b.get("w"), 1)
        bs = b.get("style") if b.get("style") in _BORDER_STYLE else "solid"
        bc = b["color"].strip() if _hexok(b.get("color")) else "#cfe5f6"
        p.append(f"border:{_fmt_num(bw)}px {bs} {bc}")
        r = _num(b.get("radius"))
        if r:
            p.append(f"border-radius:{_fmt_num(r)}px")
    if type_ in ("text", "field", "heading"):
        p.append("white-space:pre-wrap")
    return ";".join(p)


# --- generic element renderers (settings-based) ----------------------------

def _e_heading(doc, b, s, ctx):
    return _esc(s.get("text") or "")


def _e_text(doc, b, s, ctx):
    return _esc(s.get("text") or "")


def _e_field(doc, b, s, ctx):
    return _esc((s.get("prefix") or "") + _field_value(doc, s.get("field")))


def _e_image(doc, b, s, ctx):
    src = s.get("src") or ""
    if not src:
        return ""
    w = _num(s.get("width"), 40)
    return f'<img src="{_esc(src)}" style="width:{_fmt_num(w)}%">'


def _e_divider(doc, b, s, ctx):
    th = _num(s.get("thickness"), 1)
    st = s.get("lstyle") if s.get("lstyle") in _BORDER_STYLE else "solid"
    col = s["color"].strip() if _hexok(s.get("color")) else "#cfe5f6"
    return f'<div style="border-top:{_fmt_num(th)}px {st} {col}"></div>'


def _e_box(doc, b, s, ctx):
    from frappe.utils.html_utils import sanitize_html
    raw = s.get("html") or ""
    return sanitize_html(raw) if raw else ""


def _e_table(doc, b, s, ctx):
    cols = s.get("cols") or []
    rows = s.get("rows") or []
    hb = b.get("navy") if s.get("headerBg") == "navy" else b.get("primary")
    th = "".join(
        f'<th style="background-color:{hb} !important;color:#fff;padding:5px 8px;text-align:left;'
        f'border:1px solid {hb};font-weight:600;-webkit-print-color-adjust:exact;">{_esc(c)}</th>'
        for c in cols
    )
    body = []
    for r in rows:
        r = r if isinstance(r, (list, tuple)) else []
        tds = "".join(
            f'<td style="padding:5px 8px;border:1px solid #cfe5f6;">{_esc(r[ci] if ci < len(r) else "")}</td>'
            for ci in range(len(cols))
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:8pt;table-layout:fixed;word-wrap:break-word;">'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _e_spacer(doc, b, s, ctx):
    return f'<div style="height:{_fmt_num(_num(s.get("height"), 8))}mm"></div>'


# --- smart blocks honoring builder settings --------------------------------

def _d_header_banner(doc, b, s, ctx):
    if b.get("header_image"):
        return f'<img src="{_esc(b.get("header_image"))}" style="width:100%;height:100%;object-fit:cover;display:block">'
    return f'<div style="width:100%;height:100%;background:{b.get("primary", "#1C75BC")};-webkit-print-color-adjust:exact;print-color-adjust:exact;"></div>'


def _d_footer_banner(doc, b, s, ctx):
    if b.get("footer_image"):
        return f'<img src="{_esc(b.get("footer_image"))}" style="width:100%;height:100%;object-fit:cover;display:block">'
    return f'<div style="width:100%;height:100%;background:{b.get("navy", "#1A1E2A")};-webkit-print-color-adjust:exact;print-color-adjust:exact;"></div>'


def _d_title(doc, b, s, ctx):
    navy = b.get("navy", "#1A1E2A")
    primary = b.get("primary", "#1C75BC")
    left = f'<div class="bs-title" style="color:{navy}">{_esc(s.get("text") or "QUOTATION")}</div>'
    if s.get("showArabic", True):
        left += f'<div class="bs-title-ar" style="color:{primary}">{_esc(s.get("arabic") or "عرض سعر")}</div>'
    meta_cfg = s.get("meta") or {"name": True, "date": True, "valid_till": True}
    m = []
    if meta_cfg.get("name"):
        m.append(("Quotation No", doc.name))
    if meta_cfg.get("date"):
        m.append(("Date", doc.get_formatted("transaction_date")))
    if meta_cfg.get("valid_till") and doc.get("valid_till"):
        m.append(("Valid Till", doc.get_formatted("valid_till")))
    rows = "".join(f'<tr><td class="k">{_esc(k)}</td><td><bdi>{_esc(v)}</bdi></td></tr>' for k, v in m)
    if s.get("align") == "center":
        return f'<div style="text-align:center">{left}</div>'
    return (
        f'<table class="bs-head"><tr><td style="text-align:left">{left}</td>'
        f'<td style="text-align:right"><table class="bs-meta">{rows}</table></td></tr></table>'
    )


def _d_customer(doc, b, s, ctx):
    primary = b.get("primary", "#1C75BC")
    name = _esc(doc.get("customer_name") or doc.get("party_name") or "")
    heading = _esc(s.get("heading") or "Quotation To")
    out = [f'<div class="bs-billto"><div class="lbl" style="color:{primary}">{heading}</div><div class="name">{name}</div>']
    addr = doc.get("address_display")
    if addr:
        from frappe.utils.html_utils import sanitize_html
        out.append(f'<div class="addr">{sanitize_html(addr)}</div>')
    out.append("</div>")
    return "".join(out)


def _d_items(doc, b, s, ctx):
    cols_cfg = s.get("cols") or {"desc": True, "qty": True, "rate": True, "amount": True}
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    hc = navy if s.get("headerColor") == "navy" else primary
    zebra = s.get("zebra", True)

    w = s.get("widths") or {}

    def th(txt, cls=""):
        return f'<th class="{cls}" style="background-color:{hc} !important;-webkit-print-color-adjust:exact;">{txt}</th>'

    # column widths: explicit mm (from the builder) overrides the sensible % default
    coldefs = [("num", "6%"), ("item", "40%")]
    heads = th("#") + th("Item &amp; Description", "")
    if cols_cfg.get("qty"):
        coldefs.append(("qty", "12%")); heads += th("Qty", "num")
    if cols_cfg.get("rate"):
        coldefs.append(("rate", "20%")); heads += th("Rate", "num")
    if cols_cfg.get("amount"):
        coldefs.append(("amount", "22%")); heads += th("Amount", "num")
    colgroup = "<colgroup>" + "".join(
        (f'<col style="width:{_fmt_num(w[k])}mm">' if w.get(k) else f'<col style="width:{pct}">')
        for k, pct in coldefs
    ) + "</colgroup>"
    body = []
    for i, it in enumerate(doc.get("items") or [], start=1):
        name_txt = frappe.utils.strip_html_tags(it.item_name or "").strip()
        nm = _esc(name_txt)
        desc = it.get("description") or ""
        desc_txt = frappe.utils.strip_html_tags(desc).strip() if desc else ""
        dh = ""
        if cols_cfg.get("desc", True) and desc_txt and desc_txt != name_txt:
            dh = f'<div class="it-desc">{_esc(desc_txt)}</div>'
        tds = f'<td class="num">{i}</td><td><div class="it-name">{nm}</div>{dh}</td>'
        if cols_cfg.get("qty"):
            tds += f'<td class="num"><bdi>{_esc(it.get_formatted("qty"))} {_esc(it.get("uom") or "")}</bdi></td>'
        if cols_cfg.get("rate"):
            tds += f'<td class="num"><bdi>{_esc(it.get_formatted("rate"))}</bdi></td>'
        if cols_cfg.get("amount"):
            tds += f'<td class="num"><bdi>{_esc(it.get_formatted("amount"))}</bdi></td>'
        body.append(f"<tr>{tds}</tr>")
    cls = "bs-items" if zebra else "bs-items nozebra"
    return f'<table class="{cls}">{colgroup}<thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _d_datatable(doc, b, s, ctx):
    """Generic table from ANY child table on the doc: chosen columns, per-column width + align."""
    table = s.get("table") or "items"
    columns = [c for c in (s.get("columns") or []) if isinstance(c, dict) and c.get("field")]
    if not columns:
        return ""
    # Safety: only render standard (permlevel 0) child fields so a saved format can never leak a
    # permission-gated column (e.g. cost/valuation) to whoever prints the document.
    try:
        tf = doc.meta.get_field(table)
        if tf and tf.options:
            allowed = {"idx"} | {cf.fieldname for cf in frappe.get_meta(tf.options).fields
                                 if cf.fieldname and (cf.permlevel or 0) == 0}
            columns = [c for c in columns if c.get("field") in allowed]
    except Exception:
        pass
    if not columns:
        return ""
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    hc = navy if s.get("headerColor") == "navy" else primary
    zebra = s.get("zebra", True)
    rows = doc.get(table) or []
    colgroup = "<colgroup>" + "".join(
        (f'<col style="width:{_fmt_num(c.get("width"))}mm">' if c.get("width") else "<col>") for c in columns
    ) + "</colgroup>"
    heads = "".join(
        f'<th style="background-color:{hc} !important;color:#fff !important;text-align:{(c.get("align") or "left")};'
        f'font-weight:600;font-size:7.5pt;padding:6px 8px;word-wrap:break-word;-webkit-print-color-adjust:exact;">'
        f'{_esc(c.get("label") or c.get("field"))}</th>'
        for c in columns
    )
    body = []
    for i, row in enumerate(rows, start=1):
        tds = ""
        for c in columns:
            f = c.get("field")
            if f == "idx":
                val = str(getattr(row, "idx", i) or i)
            else:
                try:
                    val = row.get_formatted(f)
                except Exception:
                    val = row.get(f)
                val = "" if val is None else frappe.utils.strip_html_tags(str(val)).strip()
            align = c.get("align") or "left"
            tds += (f'<td style="text-align:{align};padding:6px 8px;border-bottom:1px solid #cfe5f6;'
                    f'word-wrap:break-word;"><bdi>{_esc(val)}</bdi></td>')
        body.append(f"<tr>{tds}</tr>")
    cls = "bs-items" if zebra else "bs-items nozebra"
    return f'<table class="{cls}">{colgroup}<thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _d_totals(doc, b, s, ctx):
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    gc = navy if s.get("grandColor") == "navy" else primary
    lines = [f'<tr><td class="lbl">Subtotal</td><td class="val"><bdi>{_esc(doc.get_formatted("total"))}</bdi></td></tr>']
    if doc.get("discount_amount"):
        lines.append(f'<tr><td class="lbl">Discount</td><td class="val"><bdi>- {_esc(doc.get_formatted("discount_amount"))}</bdi></td></tr>')
    for tax in (doc.get("taxes") or []):
        if tax.tax_amount:
            d = _esc(frappe.utils.strip_html_tags(tax.description or ""))
            lines.append(f'<tr><td class="lbl">{d}</td><td class="val"><bdi>{_esc(tax.get_formatted("tax_amount"))}</bdi></td></tr>')
    grand = (
        f'<tr class="grand"><td style="background-color:{gc} !important;color:#fff !important;font-weight:700;font-size:10pt;text-align:right;padding:6px 8px;-webkit-print-color-adjust:exact;">Grand Total</td>'
        f'<td style="background-color:{gc} !important;color:#fff !important;font-weight:700;font-size:10pt;text-align:right;white-space:nowrap;padding:6px 8px;-webkit-print-color-adjust:exact;"><bdi>{_esc(doc.get_formatted("grand_total"))}</bdi></td></tr>'
    )
    return (
        '<table style="width:100%;border-collapse:collapse;"><tr><td style="border:0;"></td>'
        '<td style="border:0;width:82mm;"><table class="bs-tot">' + "".join(lines) + grand + "</table></td></tr></table>"
    )


def _d_payment_schedule(doc, b, s, ctx):
    if not doc.get("payment_schedule"):
        return ""
    primary = b.get("primary", "#1C75BC")

    def th(txt, cls="", w=""):
        wcss = f"width:{w};" if w else ""
        return f'<th class="{cls}" style="background-color:{primary} !important;{wcss}-webkit-print-color-adjust:exact;">{txt}</th>'

    heads = th("#", "num", "6%") + th("Payment Term", "", "46%") + th("Due Date", "num", "18%") + th("Portion %", "num", "12%") + th("Amount", "num", "18%")
    body = []
    for i, ps in enumerate(doc.payment_schedule, start=1):
        term = _esc(ps.get("payment_term") or ps.get("description") or "")
        body.append(
            f'<tr><td class="num">{i}</td><td><div class="it-name">{term}</div></td>'
            f'<td class="num"><bdi>{_esc(ps.get_formatted("due_date"))}</bdi></td>'
            f'<td class="num"><bdi>{_esc(ps.get_formatted("invoice_portion"))}</bdi></td>'
            f'<td class="num"><bdi>{_esc(ps.get_formatted("payment_amount"))}</bdi></td></tr>'
        )
    return (
        f'<div class="bs-sec-lbl">Payment Schedule</div>'
        f'<table class="bs-items"><thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _d_terms(doc, b, s, ctx):
    terms_html = ctx.get("terms_html") or ""
    if not terms_html:
        return ""
    heading = _esc(s.get("heading") or "Terms & Conditions")
    return f'<div style="font-size:7.5pt;color:#6b6b6e;line-height:1.5;"><div class="bs-sec-lbl">{heading}</div>{terms_html}</div>'


def _d_signature(doc, b, s, ctx):
    label = _esc(s.get("label") or "Authorized Signature")
    return (
        '<table style="width:100%;border-collapse:collapse;"><tr><td style="border:0;"></td>'
        f'<td style="border:0;width:60mm;text-align:center;"><div class="bs-sign-box">{label}</div></td></tr></table>'
    )


def _e_pagenum(doc, b, s, ctx):
    # {p}=current page, {n}=total. ctx carries them; defaults to 1/1 (single page until merge).
    fmt = s.get("format") or "Page {p} of {n}"
    return _esc(fmt).replace("{p}", str(ctx.get("page", 1))).replace("{n}", str(ctx.get("total", 1)))


def _render_child(doc, b, c, ctx):
    """Render one block nested inside a Row column. (Nested datatable/items children still enforce
    their own permlevel filtering via the DEF_RENDERERS dispatch below.)"""
    if not isinstance(c, dict):
        return ""
    if c.get("type") == "row":
        return ""  # rows cannot nest inside rows — prevents unbounded recursion / stack overflow
    fn = DEF_RENDERERS.get(c.get("type"))
    if not fn:
        return ""
    inner = fn(doc, b, c.get("settings") or {}, ctx)
    wrap = _style_css(c.get("style") or {}, c.get("type"))
    return f'<div style="margin-bottom:2mm;{wrap}">{inner}</div>'


def _d_row(doc, b, s, ctx):
    """A row split into 2-3 columns; each column flows its own nested blocks (side-by-side layout)."""
    cols = max(1, min(3, int(_num(s.get("cols"), 2) or 2)))
    gap = max(0.0, _num(s.get("gap"), 6) or 0)
    widths = s.get("widths") or []
    cells = s.get("cells") or []
    half = _fmt_num(gap / 2.0)
    tds = []
    for i in range(cols):
        w = _num(widths[i]) if i < len(widths) else None
        wcss = f"width:{_fmt_num(w)}mm;" if w else ""
        children = cells[i] if i < len(cells) and isinstance(cells[i], list) else []
        inner = "".join(_render_child(doc, b, c, ctx) for c in children)
        lp = "0" if i == 0 else half
        rp = "0" if i == cols - 1 else half
        tds.append(f'<td style="vertical-align:top;{wcss}padding:0 {rp}mm 0 {lp}mm;">{inner}</td>')
    return f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr>{"".join(tds)}</tr></table>'


DEF_RENDERERS = {
    "header_banner": _d_header_banner,
    "footer_banner": _d_footer_banner,
    "title": _d_title,
    "customer": _d_customer,
    "items": _d_items,
    "datatable": _d_datatable,
    "row": _d_row,
    "totals": _d_totals,
    "payment_schedule": _d_payment_schedule,
    "terms": _d_terms,
    "signature": _d_signature,
    "heading": _e_heading,
    "text": _e_text,
    "field": _e_field,
    "image": _e_image,
    "divider": _e_divider,
    "box": _e_box,
    "table": _e_table,
    "pagenum": _e_pagenum,
    "spacer": _e_spacer,
    "custom_html": _e_box,  # back-compat: old custom_html == box content
}


def _branding_from_def(definition, doc):
    from brandpdf import resolver
    b = resolver.resolve_branding(doc)
    dbr = definition.get("branding") or {}
    if _hexok(dbr.get("primary")):
        b["primary"] = dbr["primary"].strip()
    if _hexok(dbr.get("navy")):
        b["navy"] = dbr["navy"].strip()
    if dbr.get("header_image"):
        b["header_image"] = dbr["header_image"]
    if dbr.get("footer_image"):
        b["footer_image"] = dbr["footer_image"]
    if dbr.get("font") in _FONTS:  # allow-list: font is interpolated into a <style> block
        b["font"] = dbr["font"]
    return b


def collect_image_srcs(definition):
    """Every image src referenced by the definition, so render_html can allow-list them for
    inlining (path traversal is still blocked downstream by assets._safe_local_path)."""
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            return set()
    if not isinstance(definition, dict):
        return set()
    srcs = set()
    dbr = definition.get("branding") or {}
    for k in ("header_image", "footer_image"):
        if dbr.get(k):
            srcs.add(dbr[k])
    for bl in definition.get("blocks") or []:
        if bl.get("type") == "image":
            src = (bl.get("settings") or {}).get("src")
            if src:
                srcs.add(src)
    return srcs


def render_definition(doc, definition, terms_html=""):
    """Render a builder DEFINITION (dict or JSON str) to HTML — matches the builder preview."""
    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, dict):
        return ""
    branding = _branding_from_def(definition, doc)
    ctx = {"terms_html": terms_html}
    if definition.get("layout") == "absolute":
        return _render_absolute(doc, definition, branding, ctx)
    parts = [base_css(branding)]
    open_ = [False]

    def close():
        if open_[0]:
            parts.append("</div>")
            open_[0] = False

    def open_c():
        if not open_[0]:
            parts.append('<div class="bs-content">')
            open_[0] = True

    blocks_list = definition.get("blocks")
    if not isinstance(blocks_list, list):
        blocks_list = []
    for bl in blocks_list:
        if not isinstance(bl, dict):
            continue
        if not _visible(doc, bl):
            continue
        t = bl.get("type")
        fn = DEF_RENDERERS.get(t)
        if not fn:
            continue
        inner = fn(doc, branding, bl.get("settings") or {}, ctx)
        if t in BANNER_BLOCKS:
            close()
            parts.append(inner)
        else:
            open_c()
            wrap = _style_css(bl.get("style") or {}, t)
            parts.append(f'<div style="{wrap}">{inner}</div>' if wrap else inner)
    close()
    return "".join(parts)


def _absolute_page_html(doc, branding, blocks_list, ctx, grow=False, top_mm=0.0, bottom_mm=0.0, y_shift=0.0):
    """Render blocks absolutely positioned on an A4 page.
    grow=True -> page may flow onto multiple pages (min-height, no clipping).
    top_mm/bottom_mm reserve @page margins so a flowing body stays clear of the running header/
    footer bands on EVERY page; y_shift offsets each block's top so page-1 positions stay correct
    once a top margin is reserved."""
    font = branding.get("font") or "Montserrat"
    navy = branding.get("navy", "#1A1E2A")
    parts = [base_css(branding)]
    if top_mm or bottom_mm:
        parts.append(f"<style>@page{{margin:{_fmt_num(top_mm)}mm 0mm {_fmt_num(bottom_mm)}mm 0mm;}}</style>")
    if grow:
        container = "position:relative;width:210mm;min-height:%smm;" % _fmt_num(max(20, 297 - top_mm - bottom_mm))
    else:
        container = "position:relative;width:210mm;height:297mm;overflow:hidden;"
    parts.append(
        f'<div style="{container}'
        f"font-family:'{font}','Segoe UI',Arial,sans-serif;color:{navy};font-size:8.5pt;"
        f'-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
    )
    for bl in (blocks_list or []):
        if not isinstance(bl, dict):
            continue
        if not _visible(doc, bl):
            continue
        t = bl.get("type")
        fn = DEF_RENDERERS.get(t)
        if not fn:
            continue
        inner = fn(doc, branding, bl.get("settings") or {}, ctx)
        pos = bl.get("pos") or {}
        x = _num(pos.get("x"), 0)
        y = _num(pos.get("y"), 0) - y_shift
        w = _num(pos.get("w"), 180)
        h = _num(pos.get("h"))
        box = f"position:absolute;left:{_fmt_num(x)}mm;top:{_fmt_num(y)}mm;width:{_fmt_num(w)}mm;"
        if h:
            box += f"height:{_fmt_num(h)}mm;overflow:hidden;"
        wrap = _style_css(bl.get("style") or {}, t, absolute=True)
        parts.append(f'<div style="{box}{wrap}">{inner}</div>')
    parts.append("</div>")
    return "".join(parts)


def _flow_body_html(doc, branding, body_blocks, ctx, top_mm=0.0, bottom_mm=0.0, floats=None):
    """Body in document flow: blocks stack top-to-bottom (so a variable-length items table never
    overlaps the totals/terms below it), reserving @page top/bottom margins so the body stays
    clear of the running header/footer bands on EVERY page. `floats` are free-positioned elements
    placed absolutely (page coords) within the body — for logos/stamps/signatures/notes."""
    font = branding.get("font") or "Montserrat"
    navy = branding.get("navy", "#1A1E2A")
    parts = [base_css(branding)]
    parts.append(f"<style>@page{{size:A4;margin:{_fmt_num(top_mm)}mm 0mm {_fmt_num(bottom_mm)}mm 0mm;}}</style>")
    parts.append(
        f'<div style="position:relative;width:210mm;padding:0 14mm;font-family:\'{font}\',\'Segoe UI\',Arial,sans-serif;'
        f'color:{navy};font-size:8.5pt;-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
    )
    for bl in (body_blocks or []):
        if not isinstance(bl, dict):
            continue
        if not _visible(doc, bl):
            continue
        t = bl.get("type")
        fn = DEF_RENDERERS.get(t)
        if not fn:
            continue
        inner = fn(doc, branding, bl.get("settings") or {}, ctx)
        css = _style_css(bl.get("style") or {}, t)
        parts.append(f'<div style="margin-bottom:4mm;{css}">{inner}</div>')
    for bl in (floats or []):
        if not isinstance(bl, dict):
            continue
        if not _visible(doc, bl):
            continue
        t = bl.get("type")
        fn = DEF_RENDERERS.get(t)
        if not fn:
            continue
        inner = fn(doc, branding, bl.get("settings") or {}, ctx)
        pos = bl.get("pos") or {}
        x = _num(pos.get("x"), 0)
        y = _num(pos.get("y"), 0) - top_mm  # page coord -> container coord (container starts at the top margin)
        if y < 0:
            y = 0
        w = _num(pos.get("w"), 120)
        h = _num(pos.get("h"))
        box = f"position:absolute;left:{_fmt_num(x)}mm;top:{_fmt_num(y)}mm;width:{_fmt_num(w)}mm;"
        if h:
            box += f"height:{_fmt_num(h)}mm;overflow:hidden;"
        wrap = _style_css(bl.get("style") or {}, t, absolute=True)
        parts.append(f'<div style="{box}{wrap}">{inner}</div>')
    parts.append("</div>")
    return "".join(parts)


def _render_absolute(doc, definition, branding, ctx):
    """Free-canvas layout: every block is absolutely positioned by its pos {x,y,w,h} in mm."""
    blocks_list = definition.get("blocks")
    if not isinstance(blocks_list, list):
        blocks_list = []
    return _absolute_page_html(doc, branding, blocks_list, ctx, grow=False)


def watermark_page_html(branding, wm):
    """A full A4 page containing just a big rotated, semi-transparent watermark — merged BEHIND
    every page by compose. Empty string if no watermark text."""
    if not isinstance(wm, dict) or not wm.get("text"):
        return ""
    color = wm["color"].strip() if _hexok(wm.get("color")) else "#1A1E2A"
    op = _num(wm.get("opacity"), 8) or 8
    size = _num(wm.get("size"), 60) or 60
    angle = _num(wm.get("angle"), -35)
    font = branding.get("font") or "Montserrat"
    return (
        base_css(branding)
        + f"<div style=\"position:relative;width:210mm;height:297mm;overflow:hidden;font-family:'{font}',Arial,sans-serif;\">"
        + '<div style="position:absolute;top:0;left:0;width:210mm;height:297mm;display:flex;align-items:center;justify-content:center;">'
        + f'<div style="transform:rotate({_fmt_num(angle)}deg);font-size:{_fmt_num(size)}pt;font-weight:800;'
        + f'color:{color};opacity:{_fmt_num((op or 8) / 100.0)};white-space:nowrap;letter-spacing:2px;'
        + f'-webkit-print-color-adjust:exact;print-color-adjust:exact;">{_esc(wm.get("text"))}</div></div></div>'
    )
