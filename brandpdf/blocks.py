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


def _pf_css(top=0, bottom=0, left=0, right=0, pw=None, ph=None):
    """Page margins in the dialect the HOST's PDF pipeline actually parses. Frappe's
    read_options_from_html regexes the RAW html for `.print-format{...margin-top:Xmm;...}`, and
    print_designer's chrome generator parses the same class from the <style> soup — for both,
    this in-HTML contract wins over (or substitutes for) caller options. Values must be plain
    `margin-x:<n>mm;` — exactly this formatting. pw/ph add the page-width/height dialect for
    non-A4 (landscape) sizes."""
    size = f"page-width:{_fmt_num(pw)}mm;page-height:{_fmt_num(ph)}mm;" if (pw and ph) else ""
    return ("<style>.print-format{"
            f"margin-top:{_fmt_num(top)}mm;margin-bottom:{_fmt_num(bottom)}mm;"
            f"margin-left:{_fmt_num(left)}mm;margin-right:{_fmt_num(right)}mm;" + size +
            "}</style>")


def page_dims(definition):
    """(width_mm, height_mm) for the definition's page setup. A4 portrait unless
    page.orientation == 'landscape'."""
    pg = definition.get("page") if isinstance(definition, dict) else None
    if isinstance(pg, dict) and (pg.get("orientation") or "").lower() == "landscape":
        return 297.0, 210.0
    return 210.0, 297.0


# Curated Google Fonts (Latin + Arabic). Name -> Google css2 family spec. The builder mirrors
# this list; SYSTEM_FONTS need no web fetch. Browsers download glyph files only for families
# actually applied, so listing all in one @import is a single CSS request.
GOOGLE_FONTS = {
    "Plus Jakarta Sans": "Plus+Jakarta+Sans:wght@400;500;600;700;800",
    "Inter": "Inter:wght@400;500;600;700;800",
    "Montserrat": "Montserrat:wght@300;400;500;600;700;800",
    "Roboto": "Roboto:wght@400;500;700",
    "Open Sans": "Open+Sans:wght@400;600;700;800",
    "Lato": "Lato:wght@400;700;900",
    "Poppins": "Poppins:wght@400;500;600;700;800",
    "Cairo": "Cairo:wght@400;600;700;800",
    "Almarai": "Almarai:wght@400;700;800",
    "Tajawal": "Tajawal:wght@400;500;700;800",
    "IBM Plex Sans Arabic": "IBM+Plex+Sans+Arabic:wght@400;500;600;700",
    "Noto Kufi Arabic": "Noto+Kufi+Arabic:wght@400;600;700",
    "Amiri": "Amiri:wght@400;700",
    # Fonts used by the premium invoice/quotation gallery templates.
    "Archivo": "Archivo:wght@400;500;600;700;800",
    "Manrope": "Manrope:wght@400;500;600;700;800",
    "Newsreader": "Newsreader:ital,wght@0,400;0,500;0,600;1,400;1,500",
    "IBM Plex Mono": "IBM+Plex+Mono:wght@400;500;600",
    "Instrument Serif": "Instrument+Serif:ital@0;1",
    "Bricolage Grotesque": "Bricolage+Grotesque:wght@400;600;700;800",
}
SYSTEM_FONTS = ["Arial", "Tahoma"]
FONT_IMPORT_URL = ("https://fonts.googleapis.com/css2?"
                   + "&".join("family=" + spec for spec in GOOGLE_FONTS.values())
                   + "&display=swap")


def base_css(b, pw=210.0, ph=297.0):
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    font = b.get("font") or "Montserrat"
    _pw, _ph = _fmt_num(pw or 210), _fmt_num(ph or 297)
    return f"""<style>
  @import url('{FONT_IMPORT_URL}');
  @page {{ size: {_pw}mm {_ph}mm; margin: 0; }}
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
  table.bs-items thead th {{ background-color:{primary} !important; color:#fff !important; font-weight:600; font-size:0.9em; padding:6px 8px; text-align:left; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  table.bs-items thead th.num {{ text-align:right; }}
  table.bs-items tbody td {{ padding:6px 8px; border-bottom:1px solid #cfe5f6; vertical-align:top; font-weight:normal; }}
  table.bs-items tbody tr {{ page-break-inside:avoid; }}
  table.bs-items td.num {{ text-align:right; white-space:nowrap; }}
  table.bs-items tbody tr {{ break-inside:avoid; }}
  table.bs-items.zebra-default tbody tr:nth-child(even) td {{ background-color:#eef6fc; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  table.bs-items.nozebra tbody tr:nth-child(even) td {{ background-color:transparent !important; }}
  table.bs-items tbody td *:not(.it-name):not(.it-desc):not(.it-img):not(.it-img *) {{ font-weight:normal !important; background:transparent !important; border:0 !important; color:inherit; }}
  table.bs-items .it-name {{ font-weight:600 !important; }}
  table.bs-items .it-desc {{ color:#6b6b6e !important; font-size:7pt; line-height:1.4; }}
  table.bs-tot {{ width:100%; border-collapse:collapse; font-size:8pt; table-layout:fixed; }}
  table.bs-tot td.lbl {{ width:52%; }}
  table.bs-tot td.val {{ width:48%; }}
  table.bs-tot td {{ padding:4px 8px; border:0; }}
  table.bs-tot td.lbl {{ color:#6b6b6e; text-align:right; word-break:break-word; }}
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
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr><td style="border:0;"></td>'
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
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr><td style="border:0;"></td>'
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
_FONTS = set(GOOGLE_FONTS) | set(SYSTEM_FONTS)  # allow-list (font is injected into <style>)


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
    """Resolve a parent-doc field for Field blocks / {token} table cells. Permission-gated
    fields (permlevel > 0) never render — same safety rule as _d_datatable's column filter, so a
    saved format can't print e.g. cost/margin to whoever holds print permission (defense in
    depth on top of apply_fieldlevel_read_permissions, which does not cover every render path).
    A dotted `link_field.target_field` (e.g. customer.email_id) hops ONE link to a related doc."""
    if not field:
        return ""
    if "." in field:
        return _linked_field_value(doc, field)
    try:
        df = frappe.get_meta(doc.doctype).get_field(field)
        if df is not None and (df.permlevel or 0) != 0:
            return ""
    except Exception:
        pass  # metadata unavailable (tests/odd contexts) -> fall through
    try:
        v = doc.get_formatted(field)
    except Exception:
        v = doc.get(field)
    return "" if v is None else str(v)


def _linked_field_value(doc, field):
    """Resolve a ONE-HOP link path 'link_field.target_field' (e.g. customer.email_id). Safe by
    construction: the link field must be a permlevel-0 Link/Dynamic Link, the target field must be
    permlevel-0 (or 'name'), and the caller must have read permission on the target doctype — so a
    print format can never hop across doctypes to leak gated data."""
    link_field, _, sub = field.partition(".")
    if not link_field or not sub or "." in sub:  # one hop only
        return ""
    try:
        df = frappe.get_meta(doc.doctype).get_field(link_field)
    except Exception:
        df = None
    if not df or (df.permlevel or 0) != 0 or df.fieldtype not in ("Link", "Dynamic Link"):
        return ""
    target = doc.get(df.options) if df.fieldtype == "Dynamic Link" else df.options
    link_value = doc.get(link_field)
    if not target or not link_value or not frappe.db.exists("DocType", target):
        return ""
    try:
        sdf = frappe.get_meta(target).get_field(sub)
    except Exception:
        sdf = None
    if sub != "name" and (not sdf or (sdf.permlevel or 0) != 0):
        return ""
    try:
        if not frappe.has_permission(target, "read"):
            return ""
    except Exception:
        return ""
    try:
        tdoc = frappe.get_cached_doc(target, link_value)
        try:
            v = tdoc.get_formatted(sub)
        except Exception:
            v = tdoc.get(sub)
    except Exception:
        try:
            v = frappe.db.get_value(target, link_value, sub)
        except Exception:
            v = None
    return "" if v is None else str(v)


def _visible(doc, bl):
    """Conditional visibility: a block with a `cond` {field, op, value} renders only when the
    document's field satisfies it. No cond -> always visible.

    A block the designer hid in the builder (eye toggle in the Layers rail) never prints, whatever
    its condition says. Every render path funnels through here, so this one line is the whole rule."""
    if isinstance(bl, dict) and bl.get("hidden"):
        return False
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
    lh = _num(style.get("lineHeight"))
    if lh is not None and 0.5 <= lh <= 4:
        p.append(f"line-height:{_fmt_num(lh)}")
    ls = _num(style.get("letterSpacing"))
    if ls is not None and -5 <= ls <= 30:
        p.append(f"letter-spacing:{_fmt_num(ls)}px")
    if style.get("underline"):
        p.append("text-decoration:underline")
    if style.get("rtl"):
        p.append("direction:rtl")
        if a not in _ALIGN:
            p.append("text-align:right")
    fnt = style.get("font")
    if fnt in _FONTS:
        p.append(f"font-family:'{fnt}','Segoe UI',Arial,sans-serif")
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
        sides = b.get("sides") if isinstance(b.get("sides"), dict) else None
        if sides and not all(sides.get(k, True) for k in ("t", "r", "b", "l")):
            # per-side borders: e.g. a LEFT accent bar next to a heading block
            for key, css in (("t", "border-top"), ("r", "border-right"), ("b", "border-bottom"), ("l", "border-left")):
                if sides.get(key, True):
                    p.append(f"{css}:{_fmt_num(bw)}px {bs} {bc}")
        else:
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


_RICH_FIELDTYPES = {"Text Editor", "HTML Editor", "HTML", "Markdown Editor"}


def _field_is_rich(doc, field):
    try:
        df = frappe.get_meta(doc.doctype).get_field(field)
        return bool(df) and getattr(df, "fieldtype", "") in _RICH_FIELDTYPES
    except Exception:
        return False


def _e_field(doc, b, s, ctx):
    field = s.get("field")
    prefix = _esc(s.get("prefix") or "")
    val = _field_value(doc, field)
    if val and _field_is_rich(doc, field):
        from frappe.utils.html_utils import sanitize_html
        return prefix + sanitize_html(val)  # rich fields (e.g. Terms) print STYLED, not as raw tags
    return prefix + _esc(val)


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


_CELL_TOKEN = re.compile(r"^\{([A-Za-z0-9_.]+)\}$")  # dots allowed: one-hop link paths


def _cell_value(doc, v):
    """A cell whose whole content is '{fieldname}' is bound to that document field. Rich-text
    fields collapse to plain text here (a table cell is not a rich container)."""
    m = _CELL_TOKEN.match(str(v or "").strip())
    if m:
        val = _field_value(doc, m.group(1))
        if val and _field_is_rich(doc, m.group(1)):
            val = frappe.utils.strip_html_tags(val).strip()
        return val
    return v or ""


def _list(v):
    """Malformed-settings guard: anything that isn't a real list/tuple renders as empty."""
    return v if isinstance(v, (list, tuple)) else []


def _e_table(doc, b, s, ctx):
    cols = _list(s.get("cols"))
    rows = _list(s.get("rows"))
    hb = b.get("navy") if s.get("headerBg") == "navy" else b.get("primary")
    cstyles = _list(s.get("colStyle"))
    rstyles = _list(s.get("rowStyle"))

    def cst(ci):
        return cstyles[ci] if ci < len(cstyles) and isinstance(cstyles[ci], dict) else {}

    colgroup = "<colgroup>" + "".join(
        (f'<col style="width:{_fmt_num(_num(cst(ci).get("w")))}mm">' if _num(cst(ci).get("w")) else "<col>")
        for ci in range(len(cols))
    ) + "</colgroup>"
    def _sz(v):  # per-column/row font size in pt (clamped), else ""
        n = _num(v)
        return f"font-size:{_fmt_num(min(72, max(4, n)))}pt;" if n else ""

    # ---- table-wide borders (preset + width/color/style), overridable per column -----------
    bo = s.get("borders") if isinstance(s.get("borders"), dict) else {}
    preset = bo.get("preset") if bo.get("preset") in ("grid", "rows", "outline", "none") else "grid"
    tbw = min(10, max(0, _num(bo.get("w"), 1) or 0))
    tbc = bo["color"].strip() if _hexok(bo.get("color")) else "#cfe5f6"
    tbs = bo.get("style") if bo.get("style") in _BORDER_STYLE else "solid"

    def cell_border(st, default_color):
        """Border CSS for one cell: the column's override wins, else the table preset."""
        cbw = _num(st.get("bw"))
        cbc = st["bcolor"].strip() if _hexok(st.get("bcolor")) else None
        cbs = st.get("bstyle") if st.get("bstyle") in _BORDER_STYLE else None
        if cbw is not None or cbc or cbs:
            w_ = min(10, max(0, cbw if cbw is not None else (tbw or 1)))
            return f"border:{_fmt_num(w_)}px {cbs or tbs} {cbc or tbc};"
        if preset == "grid":
            return f"border:{_fmt_num(tbw)}px {tbs} {default_color};" if tbw else "border:0;"
        if preset == "rows":
            return f"border:0;border-bottom:{_fmt_num(tbw)}px {tbs} {default_color};" if tbw else "border:0;"
        return "border:0;"  # outline / none: no cell borders (outline drawn on the table)

    pad = s.get("cellPad") if isinstance(s.get("cellPad"), dict) else {}
    py = min(30, max(0, _num(pad.get("y"), 5)))
    px = min(30, max(0, _num(pad.get("x"), 8)))
    padding = f"padding:{_fmt_num(py)}px {_fmt_num(px)}px;"

    zebra_bg = (s.get("zebraColor").strip() if _hexok(s.get("zebraColor")) else "#eef6fc") if s.get("zebra") else None

    # Header (thead) styling: headerStyle overrides the Primary/Navy quick-pick + white text.
    hs = s.get("headerStyle") if isinstance(s.get("headerStyle"), dict) else {}
    hbg = hs["bg"].strip() if _hexok(hs.get("bg")) else hb
    hcolor = hs["color"].strip() if _hexok(hs.get("color")) else "#fff"
    hweight = str(hs.get("weight")) if str(hs.get("weight")) in _WEIGHT else "600"
    # Legacy look when no border config: th border matches the header bg. Configured -> table rules.
    th = "".join(
        f'<th style="background-color:{hbg} !important;color:{hcolor};{padding}'
        f'text-align:{_esc(cst(ci).get("align") or "left")};{_sz(hs.get("size") or cst(ci).get("size"))}'
        f'{cell_border(cst(ci), tbc if bo else hbg)}'
        f'font-weight:{hweight};-webkit-print-color-adjust:exact;">'
        f"{_esc(_cell_value(doc, cols[ci]))}</th>"
        for ci in range(len(cols))
    )
    body = []
    for ri, r in enumerate(rows):
        r = r if isinstance(r, (list, tuple)) else []
        rst = rstyles[ri] if ri < len(rstyles) and isinstance(rstyles[ri], dict) else {}
        row_bg = rst["bg"].strip() if _hexok(rst.get("bg")) else (zebra_bg if (zebra_bg and ri % 2 == 1) else None)
        trbg = f'background:{row_bg};-webkit-print-color-adjust:exact;' if row_bg else ""
        rh = _num(rst.get("h"))
        height = f"height:{_fmt_num(min(100, max(1, rh)))}mm;" if rh else ""
        tds = ""
        for ci in range(len(cols)):
            st = cst(ci)
            weight = rst.get("weight") or st.get("weight") or "normal"
            color = f'color:{_esc(st["color"])};' if _hexok(st.get("color")) else ""
            size = _sz(rst.get("size") or st.get("size"))  # row size wins over column size
            # bg precedence: explicit row bg (on the tr) > column bg > zebra (on the tr)
            colbg = f'background-color:{st["bg"].strip()};-webkit-print-color-adjust:exact;' \
                if (_hexok(st.get("bg")) and not _hexok(rst.get("bg"))) else ""
            tds += (f'<td style="{padding}{cell_border(st, tbc)}{height}'
                    f'text-align:{_esc(st.get("align") or "left")};font-weight:{_esc(weight)};{color}{size}{colbg}'
                    f'word-wrap:break-word;">{_esc(_cell_value(doc, r[ci] if ci < len(r) else ""))}</td>')
        body.append(f'<tr style="{trbg}">{tds}</tr>')
    outline = f"border:{_fmt_num(tbw)}px {tbs} {tbc};" if (preset == "outline" and tbw) else ""
    collapse = "border-collapse:collapse;"
    hr = _num(hs.get("radius"))
    if hr:
        r_ = _fmt_num(min(30, max(0, hr)))
        th = th.replace('style="', f'style="border-top-left-radius:{r_}px;border-bottom-left-radius:{r_}px;', 1)
        k = th.rfind('style="')
        th = th[:k] + f'style="border-top-right-radius:{r_}px;border-bottom-right-radius:{r_}px;' + th[k + 7:]
        collapse = "border-collapse:separate;border-spacing:0;"  # collapse ignores radius
    return (
        f'<table style="width:100%;{collapse}table-layout:fixed;word-wrap:break-word;{outline}">'
        f"{colgroup}<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"
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
    tc = s["titleColor"].strip() if _hexok(s.get("titleColor")) else navy
    tsz = _num(s.get("titleSize"))
    tszc = f"font-size:{_fmt_num(min(72, max(6, tsz)))}pt;" if tsz else ""
    ac = s["arabicColor"].strip() if _hexok(s.get("arabicColor")) else primary
    left = f'<div class="bs-title" style="color:{tc};{tszc}">{_esc(s.get("text") or "QUOTATION")}</div>'
    if s.get("showArabic", True):
        left += f'<div class="bs-title-ar" style="color:{ac}">{_esc(s.get("arabic") or "عرض سعر")}</div>'
    meta_cfg = s.get("meta") or {"name": True, "date": True, "valid_till": True}
    ml = s.get("metaLabels") if isinstance(s.get("metaLabels"), dict) else {}
    m = []
    if meta_cfg.get("name"):
        m.append((ml.get("name") or "Quotation No", doc.name))
    if meta_cfg.get("date"):
        m.append((ml.get("date") or "Date", doc.get_formatted("transaction_date")))
    if meta_cfg.get("valid_till") and doc.get("valid_till"):
        m.append((ml.get("valid_till") or "Valid Till", doc.get_formatted("valid_till")))
    mlc = f'color:{s["metaLabelColor"].strip()};' if _hexok(s.get("metaLabelColor")) else ""
    mvc = f'color:{s["metaValueColor"].strip()};' if _hexok(s.get("metaValueColor")) else ""
    mbc = f'border-color:{s["metaBorderColor"].strip()};' if _hexok(s.get("metaBorderColor")) else ""
    rows = "".join(
        f'<tr><td class="k" style="{mlc}{mbc}">{_esc(k)}</td><td style="{mvc}{mbc}"><bdi>{_esc(v)}</bdi></td></tr>'
        for k, v in m)
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
    hcol = s["headingColor"].strip() if _hexok(s.get("headingColor")) else primary
    ncol = f'color:{s["nameColor"].strip()};' if _hexok(s.get("nameColor")) else ""
    nsz = _num(s.get("nameSize"))
    nszc = f"font-size:{_fmt_num(min(72, max(4, nsz)))}pt;" if nsz else ""
    out = [f'<div class="bs-billto"><div class="lbl" style="color:{hcol}">{heading}</div><div class="name" style="{ncol}{nszc}">{name}</div>']
    addr = doc.get("address_display")
    if addr:
        from frappe.utils.html_utils import sanitize_html
        clean = sanitize_html(addr)
        # address_display often ends in empty <br> lines (blank phone/email slots) — they print
        # as a mystery gap under the address, especially inside a padded/bordered card.
        clean = re.sub(r"(?:\s|&nbsp;|<br\s*/?>)+$", "", clean, flags=re.I)
        if clean:
            acol = f'color:{s["addrColor"].strip()};' if _hexok(s.get("addrColor")) else ""
            asz = _num(s.get("addrSize"))
            aszc = f"font-size:{_fmt_num(min(72, max(4, asz)))}pt;" if asz else ""
            out.append(f'<div class="addr" style="{acol}{aszc}">{clean}</div>')
    out.append("</div>")
    return "".join(out)


def _tbl_skin(s, b, default_hbg):
    """Shared override skin for the READY tables (items/payment/datatable): returns inline-CSS
    fragments that are EMPTY when unconfigured (class defaults keep the legacy look).
    keys: th (header cells), th_first/th_last (radius), td_border, pad, num (numeric cells),
    table (element style e.g. border-collapse for radius / outline)."""
    out = {"th": "", "th_first": "", "th_last": "", "td_border": "", "pad": "", "num": "", "table": ""}
    hs = s.get("headerStyle") if isinstance(s.get("headerStyle"), dict) else {}
    if _hexok(hs.get("bg")):
        out["th"] += f'background-color:{hs["bg"].strip()} !important;'
    else:
        out["th"] += f'background-color:{default_hbg} !important;'
    if _hexok(hs.get("color")):
        out["th"] += f'color:{hs["color"].strip()} !important;'
    n = _num(hs.get("size"))
    if n:
        out["th"] += f"font-size:{_fmt_num(min(72, max(4, n)))}pt;"
    if str(hs.get("weight")) in _WEIGHT:
        out["th"] += f'font-weight:{hs.get("weight")};'
    r = _num(hs.get("radius"))
    if r:
        r = _fmt_num(min(30, max(0, r)))
        out["th_first"] = f"border-top-left-radius:{r}px;border-bottom-left-radius:{r}px;"
        out["th_last"] = f"border-top-right-radius:{r}px;border-bottom-right-radius:{r}px;"
        out["table"] += "border-collapse:separate;border-spacing:0;"  # collapse ignores radius
    bo = s.get("borders") if isinstance(s.get("borders"), dict) else {}
    if bo:
        preset = bo.get("preset") if bo.get("preset") in ("grid", "rows", "outline", "none") else "rows"
        w_ = min(10, max(0, _num(bo.get("w"), 1) or 0))
        c_ = bo["color"].strip() if _hexok(bo.get("color")) else "#cfe5f6"
        st_ = bo.get("style") if bo.get("style") in _BORDER_STYLE else "solid"
        if preset == "grid" and w_:
            out["td_border"] = f"border:{_fmt_num(w_)}px {st_} {c_};"
        elif preset == "rows" and w_:
            out["td_border"] = f"border:0;border-bottom:{_fmt_num(w_)}px {st_} {c_};"
        else:
            out["td_border"] = "border:0;"
            if preset == "outline" and w_:
                out["table"] += f"border:{_fmt_num(w_)}px {st_} {c_};"
    pad = s.get("cellPad") if isinstance(s.get("cellPad"), dict) else {}
    if pad:
        py = min(30, max(0, _num(pad.get("y"), 6)))
        px = min(30, max(0, _num(pad.get("x"), 8)))
        out["pad"] = f"padding:{_fmt_num(py)}px {_fmt_num(px)}px;"
    ns = s.get("numStyle") if isinstance(s.get("numStyle"), dict) else {}
    if _hexok(ns.get("color")):
        out["num"] += f'color:{ns["color"].strip()} !important;'
    n = _num(ns.get("size"))
    if n:
        out["num"] += f"font-size:{_fmt_num(min(72, max(4, n)))}pt;"
    if str(ns.get("weight")) in _WEIGHT:
        out["num"] += f'font-weight:{ns.get("weight")} !important;'
    return out


def _col_css(sett, key, numeric):
    """Inline CSS for ONE ready-table column: settings.colStyles[key] {color,size,weight,align}
    wins; numeric columns fall back to the legacy aggregate settings.numStyle."""
    cs = sett.get("colStyles") if isinstance(sett.get("colStyles"), dict) else {}
    st = cs.get(key) if isinstance(cs.get(key), dict) else {}
    if not st and numeric:
        st = sett.get("numStyle") if isinstance(sett.get("numStyle"), dict) else {}
    out = ""
    if _hexok(st.get("color")):
        out += f'color:{st["color"].strip()} !important;'
    n = _num(st.get("size"))
    if n:
        out += f"font-size:{_fmt_num(min(72, max(4, n)))}pt;"
    if str(st.get("weight")) in _WEIGHT:
        out += f'font-weight:{st.get("weight")} !important;'
    if st.get("align") in _ALIGN:
        out += f'text-align:{st.get("align")};'
    if _hexok(st.get("bg")):
        out += f'background-color:{st["bg"].strip()};-webkit-print-color-adjust:exact;'
    return out


def _zebra_parts(s):
    """(table_class, even_row_inline_bg) honoring settings.zebra + settings.zebraColor."""
    if not s.get("zebra", True):
        return "bs-items nozebra", ""
    zc = s.get("zebraColor")
    if _hexok(zc):
        return "bs-items", f"background-color:{zc.strip()};-webkit-print-color-adjust:exact;"
    return "bs-items zebra-default", ""


def _d_items(doc, b, s, ctx):
    cols_cfg = s.get("cols") or {"desc": True, "qty": True, "rate": True, "amount": True}
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    hc = navy if s.get("headerColor") == "navy" else primary
    zcls, zbg = _zebra_parts(s)
    zebra = s.get("zebra", True)
    sk = _tbl_skin(s, b, hc)

    w = s.get("widths") if isinstance(s.get("widths"), dict) else {}

    def th(txt, cls=""):
        return (f'<th class="{cls}" style="{sk["th"]}{sk["pad"]}{sk["td_border"]}'
                f'-webkit-print-color-adjust:exact;">{txt}</th>')

    # column widths: explicit mm (from the builder) overrides the sensible % default
    lb = s.get("labels") if isinstance(s.get("labels"), dict) else {}

    def L(k, d):  # editable column titles (settings.labels), defaulting to the classics
        return _esc(lb.get(k) or d)

    coldefs = [("num", "6%"), ("item", "40%")]
    heads = th(L("num", "#")) + th(L("item", "Item & Description"), "")
    if cols_cfg.get("qty"):
        coldefs.append(("qty", "12%")); heads += th(L("qty", "Qty"), "num")
    if cols_cfg.get("rate"):
        coldefs.append(("rate", "20%")); heads += th(L("rate", "Rate"), "num")
    if cols_cfg.get("amount"):
        coldefs.append(("amount", "22%")); heads += th(L("amount", "Amount"), "num")
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
        base_td = sk["pad"] + sk["td_border"]
        c_num = base_td + _col_css(s, "num", True)
        c_item = base_td + _col_css(s, "item", False)
        c_qty = base_td + _col_css(s, "qty", True)
        c_rate = base_td + _col_css(s, "rate", True)
        c_amount = base_td + _col_css(s, "amount", True)
        ds = s.get("descStyle") if isinstance(s.get("descStyle"), dict) else {}
        dcss = (f'color:{ds["color"].strip()} !important;' if _hexok(ds.get("color")) else "") +                (f"font-size:{_fmt_num(min(72, max(4, _num(ds.get('size')))))}pt;" if _num(ds.get("size")) else "")
        if dh and dcss:
            dh = dh.replace('class="it-desc"', f'class="it-desc" style="{dcss}"')
        # Optional product photo above the name (settings.showImage): the item row's own `image`
        # attach. Rows without an image (services, section lines) get no box — matching how a
        # product-catalog quotation reads.
        ih = ""
        ipos = str(s.get("imgPos") or "top").lower()
        if ipos not in ("top", "left", "right"):
            ipos = "top"
        iw = _fmt_num(min(180, max(15, _num(s.get("imgW"), 58))))   # up to full column width
        if s.get("showImage"):
            src = it.get("image") or ""
            if src and (str(src).startswith("/files/") or str(src).startswith("/private/files/")):
                iht = _fmt_num(min(150, max(10, _num(s.get("imgH"), 40))))
                mg = "margin:1mm 0 1.5mm;" if ipos == "top" else "margin:0;"
                ih = (f'<div class="it-img" style="{mg}"><img src="{_esc(src)}" '
                      f'style="width:{iw}mm;height:{iht}mm;object-fit:contain;background:#fff;'
                      f'border:1px solid #e8ebee;border-radius:8px;display:block;"></div>')
        txt = f'<div class="it-name">{nm}</div>{dh}'
        # Beside the text: a nested table, not flexbox — it lays out identically in Chromium AND
        # wkhtmltopdf (the landscape fallback), so the canvas and the PDF cannot drift apart.
        if ih and ipos in ("left", "right"):
            pad = "padding:0 0 0 3mm;" if ipos == "left" else "padding:0 3mm 0 0;"
            icell = f'<td style="border:0;padding:0;width:{iw}mm;vertical-align:top;">{ih}</td>'
            tcell = f'<td style="border:0;{pad}vertical-align:top;">{txt}</td>'
            inner_cell = ('<table style="width:100%;border-collapse:collapse;border:0;"><tr>'
                          + (icell + tcell if ipos == "left" else tcell + icell)
                          + "</tr></table>")
        else:
            inner_cell = ih + txt
        tds = f'<td class="num" style="{c_num}">{i}</td><td style="{c_item}">{inner_cell}</td>'
        if cols_cfg.get("qty"):
            tds += f'<td class="num" style="{c_qty}"><bdi>{_esc(it.get_formatted("qty"))} {_esc(it.get("uom") or "")}</bdi></td>'
        if cols_cfg.get("rate"):
            tds += f'<td class="num" style="{c_rate}"><bdi>{_esc(it.get_formatted("rate"))}</bdi></td>'
        if cols_cfg.get("amount"):
            tds += f'<td class="num" style="{c_amount}"><bdi>{_esc(it.get_formatted("amount"))}</bdi></td>'
        rowstyle = f' style="{zbg}"' if (zbg and i % 2 == 0) else ""
        body.append(f"<tr{rowstyle}>{tds}</tr>")
    if sk["th_first"]:  # rounded first/last header cells
        heads = heads.replace('style="', 'style="' + sk["th_first"], 1)
        k = heads.rfind('style="')
        heads = heads[:k] + 'style="' + sk["th_last"] + heads[k + 7:]
    return f'<table class="{zcls}" style="{sk["table"]}">{colgroup}<thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _d_datatable(doc, b, s, ctx):
    """Generic table from ANY child table on the doc: chosen columns, per-column width + align."""
    table = s.get("table") or "items"
    columns = [c for c in _list(s.get("columns")) if isinstance(c, dict) and c.get("field")]
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
    sk = _tbl_skin(s, b, hc)
    hs_size = _num((s.get("headerStyle") or {}).get("size")) if isinstance(s.get("headerStyle"), dict) else None
    th_extra = ("" if hs_size else "font-size:7.5pt;") + (sk["pad"] or "padding:6px 8px;") + sk["td_border"]
    heads = "".join(
        f'<th style="{sk["th"]}{"color:#fff !important;" if "color:" not in sk["th"] else ""}'
        f'text-align:{(c.get("align") or "left")};font-weight:600;{th_extra}'
        f'word-wrap:break-word;-webkit-print-color-adjust:exact;">'
        f'{_esc(c.get("label") or c.get("field"))}</th>'
        for c in columns
    )
    if sk["th_first"]:
        heads = heads.replace('style="', 'style="' + sk["th_first"], 1)
        k = heads.rfind('style="')
        heads = heads[:k] + 'style="' + sk["th_last"] + heads[k + 7:]
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
            td_pad = sk["pad"] or "padding:6px 8px;"
            td_bor = sk["td_border"] or "border-bottom:1px solid #cfe5f6;"
            td_num = sk["num"] if align == "right" else ""
            tds += (f'<td style="text-align:{align};{td_pad}{td_bor}{td_num}'
                    f'word-wrap:break-word;"><bdi>{_esc(val)}</bdi></td>')
        body.append(f"<tr>{tds}</tr>")
    zcls, zbg = _zebra_parts(s)
    if zbg:
        body = [(f'<tr style="{zbg}">' + r[4:]) if (i % 2 == 1) else r for i, r in enumerate(body)]
    return f'<table class="{zcls}" style="{sk["table"]}">{colgroup}<thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _d_totals(doc, b, s, ctx):
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    gc = s["grandBg"].strip() if _hexok(s.get("grandBg")) else (navy if s.get("grandColor") == "navy" else primary)
    gtc = s["grandTextColor"].strip() if _hexok(s.get("grandTextColor")) else "#fff"
    gsz = _num(s.get("grandSize"))
    gszc = f"font-size:{_fmt_num(min(72, max(4, gsz)))}pt;" if gsz else "font-size:10pt;"
    lc = f'color:{s["labelColor"].strip()};' if _hexok(s.get("labelColor")) else ""
    vc = f'color:{s["valueColor"].strip()};' if _hexok(s.get("valueColor")) else ""
    vsz = _num(s.get("valueSize"))
    vszc = f"font-size:{_fmt_num(min(72, max(4, vsz)))}pt;" if vsz else ""
    wmm = _num(s.get("width"), 82) or 82
    wmm = _fmt_num(min(200, max(40, wmm)))
    lines = [f'<tr><td class="lbl" style="{lc}{vszc}">{_esc(s.get("subtotalLabel") or "Subtotal")}</td><td class="val" style="{vc}{vszc}"><bdi>{_esc(doc.get_formatted("total"))}</bdi></td></tr>']
    if doc.get("discount_amount"):
        lines.append(f'<tr><td class="lbl" style="{lc}{vszc}">{_esc(s.get("discountLabel") or "Discount")}</td><td class="val" style="{vc}{vszc}"><bdi>- {_esc(doc.get_formatted("discount_amount"))}</bdi></td></tr>')
    for tax in (doc.get("taxes") or []):
        if tax.tax_amount:
            d = _esc(frappe.utils.strip_html_tags(tax.description or ""))
            lines.append(f'<tr><td class="lbl" style="{lc}{vszc}">{d}</td><td class="val" style="{vc}{vszc}"><bdi>{_esc(tax.get_formatted("tax_amount"))}</bdi></td></tr>')
    grand = (
        f'<tr class="grand"><td style="background-color:{gc} !important;color:{gtc} !important;font-weight:700;{gszc}text-align:right;padding:6px 8px;-webkit-print-color-adjust:exact;">{_esc(s.get("grandLabel") or "Grand Total")}</td>'
        f'<td style="background-color:{gc} !important;color:{gtc} !important;font-weight:700;{gszc}text-align:right;white-space:nowrap;padding:6px 8px;-webkit-print-color-adjust:exact;"><bdi>{_esc(doc.get_formatted("grand_total"))}</bdi></td></tr>'
    )
    return (
        f'<div style="width:{wmm}mm;max-width:100%;margin-left:auto;">'
        f'<table class="bs-tot" style="width:100%;">' + "".join(lines) + grand + "</table></div>"
    )


def _d_payment_schedule(doc, b, s, ctx):
    if not doc.get("payment_schedule"):
        return ""
    primary = b.get("primary", "#1C75BC")
    hc = b.get("navy", "#1A1E2A") if s.get("headerColor") == "navy" else primary
    sk = _tbl_skin(s, b, hc)
    zcls, zbg = _zebra_parts(s) if ("zebra" in s or _hexok(s.get("zebraColor"))) else ("bs-items", "")
    heading = _esc(s.get("heading") or "Payment Schedule")
    hcolor = f'color:{s["headingColor"].strip()};' if _hexok(s.get("headingColor")) else ""

    def th(txt, cls="", w=""):
        wcss = f"width:{w};" if w else ""
        return (f'<th class="{cls}" style="{sk["th"]}{sk["pad"]}{sk["td_border"]}{wcss}'
                f'-webkit-print-color-adjust:exact;">{txt}</th>')

    heads = th("#", "num", "6%") + th("Payment Term", "", "46%") + th("Due Date", "num", "18%") + th("Portion %", "num", "12%") + th("Amount", "num", "18%")
    if sk["th_first"]:
        heads = heads.replace('style="', 'style="' + sk["th_first"], 1)
        k = heads.rfind('style="')
        heads = heads[:k] + 'style="' + sk["th_last"] + heads[k + 7:]
    base_td = sk["pad"] + sk["td_border"]
    c_num = base_td + _col_css(s, "num", True)
    c_term = base_td + _col_css(s, "term", False)
    c_due = base_td + _col_css(s, "due", True)
    c_pct = base_td + _col_css(s, "pct", True)
    c_amount = base_td + _col_css(s, "amount", True)
    body = []
    for i, ps in enumerate(doc.payment_schedule, start=1):
        term = _esc(ps.get("payment_term") or ps.get("description") or "")
        rowstyle = f' style="{zbg}"' if (zbg and i % 2 == 0) else ""
        body.append(
            f'<tr{rowstyle}><td class="num" style="{c_num}">{i}</td><td style="{c_term}"><div class="it-name">{term}</div></td>'
            f'<td class="num" style="{c_due}"><bdi>{_esc(ps.get_formatted("due_date"))}</bdi></td>'
            f'<td class="num" style="{c_pct}"><bdi>{_esc(ps.get_formatted("invoice_portion"))}</bdi></td>'
            f'<td class="num" style="{c_amount}"><bdi>{_esc(ps.get_formatted("payment_amount"))}</bdi></td></tr>'
        )
    return (
        f'<div class="bs-sec-lbl" style="{hcolor}">{heading}</div>'
        f'<table class="{zcls}" style="{sk["table"]}"><thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _d_terms(doc, b, s, ctx):
    terms_html = ctx.get("terms_html") or ""
    if not terms_html:
        return ""
    heading = _esc(s.get("heading") or "Terms & Conditions")
    hcol = f' style="color:{s["headingColor"].strip()};"' if _hexok(s.get("headingColor")) else ""
    bcol = s["bodyColor"].strip() if _hexok(s.get("bodyColor")) else "#6b6b6e"
    bsz = _num(s.get("bodySize"))
    bsz = _fmt_num(min(72, max(4, bsz))) if bsz else "7.5"
    return f'<div style="font-size:{bsz}pt;color:{bcol};line-height:1.5;"><div class="bs-sec-lbl"{hcol}>{heading}</div>{terms_html}</div>'


def _d_signature(doc, b, s, ctx):
    label = _esc(s.get("label") or "Authorized Signature")
    bw = _fmt_num(min(160, max(25, _num(s.get("boxW"), 60) or 60)))
    lw = _fmt_num(min(6, max(0.5, _num(s.get("lineW"), 1.5) or 1.5)))
    lcol = s["lineColor"].strip() if _hexok(s.get("lineColor")) else "#0C1322"
    tcol = f'color:{s["labelColor"].strip()};' if _hexok(s.get("labelColor")) else ""
    tsz = _num(s.get("labelSize"))
    tszc = f"font-size:{_fmt_num(min(72, max(4, tsz)))}pt;" if tsz else ""
    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr><td style="border:0;"></td>'
        f'<td style="border:0;width:{bw}mm;text-align:center;"><div class="bs-sign-box" '
        f'style="border-top:{lw}px solid {lcol};{tcol}{tszc}">{label}</div></td></tr></table>'
    )


def _e_pagenum(doc, b, s, ctx):
    # {p}=current page, {n}=total. ctx carries them; defaults to 1/1 (single page until merge).
    fmt = s.get("format") or "Page {p} of {n}"
    return _esc(fmt).replace("{p}", str(ctx.get("page", 1))).replace("{n}", str(ctx.get("total", 1)))


# --- Report blocks (data source = a query/script/report-builder run, not a document) --------
# The synthetic report doc (brandpdf.report.ReportDoc) exposes doc.get("_bpdf_report") =
# {name, columns:[{fieldname,label,align,width,fieldtype}], rows:[{fieldname: display_str}],
#  filters:[{label,value}], printed_on, native_html}. Columns/rows are already normalized and
# permission-scoped upstream, so these renderers stay presentation-only.

def _report_ctx(doc):
    r = doc.get("_bpdf_report") if hasattr(doc, "get") else None
    return r if isinstance(r, dict) else {}


def _d_report_title(doc, b, s, ctx):
    navy = b.get("navy", "#1A1E2A")
    primary = b.get("primary", "#1C75BC")
    rep = _report_ctx(doc)
    tc = s["titleColor"].strip() if _hexok(s.get("titleColor")) else navy
    tsz = _num(s.get("titleSize"))
    tszc = f"font-size:{_fmt_num(min(72, max(6, tsz)))}pt;" if tsz else ""
    title = _esc(s.get("text") or rep.get("name") or "Report")
    left = f'<div class="bs-title" style="color:{tc};{tszc}">{title}</div>'
    if s.get("showDate", True) and rep.get("printed_on"):
        left += (f'<div style="color:{primary};font-size:8pt;margin-top:1mm;">'
                 f'{_esc(rep.get("printed_on"))}</div>')
    if s.get("align") == "center":
        return f'<div style="text-align:center">{left}</div>'
    return left


def _d_report_filters(doc, b, s, ctx):
    """Compact 'Filters applied' summary — one chip per active filter."""
    rep = _report_ctx(doc)
    flt = [f for f in (rep.get("filters") or []) if isinstance(f, dict) and f.get("value") not in (None, "", [])]
    if not flt:
        return ""
    primary = b.get("primary", "#1C75BC")
    lc = s["labelColor"].strip() if _hexok(s.get("labelColor")) else primary
    heading = _esc(s.get("heading") or "Filters")
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 4px 0;font-size:7.5pt;">'
        f'<b style="color:{lc};">{_esc(f.get("label"))}:</b> <bdi>{_esc(f.get("value"))}</bdi></span>'
        for f in flt
    )
    return (f'<div style="line-height:1.5;"><span class="bs-sec-lbl">{heading}</span> {chips}</div>')


def _d_report_native(doc, b, s, ctx):
    """Mode A wrapper: drop the framework-rendered report table in as-is (branded pages around
    it). ctx['report_html'] is server-produced HTML (query report print view); sanitize as a
    belt-and-braces measure since it is embedded into our composed page."""
    html = ctx.get("report_html") or _report_ctx(doc).get("native_html") or ""
    if not html:
        return ""
    from frappe.utils.html_utils import sanitize_html
    try:
        html = sanitize_html(html)
    except Exception:
        pass
    return f'<div class="bs-report-native" style="font-size:8pt;">{html}</div>'


def _d_report_table(doc, b, s, ctx):
    """Mode B: a fully styled table built from the report's columns/rows, with per-column
    show/hide/reorder/width/align chosen in the builder (settings.columns). No selection ->
    every report column, in order."""
    rep = _report_ctx(doc)
    all_cols = [c for c in (rep.get("columns") or []) if isinstance(c, dict) and c.get("fieldname")]
    rows = rep.get("rows") or []
    sel = [c for c in _list(s.get("columns")) if isinstance(c, dict) and c.get("field")]
    if sel:
        by = {c.get("fieldname"): c for c in all_cols}
        cols = []
        for c in sel:
            src = by.get(c.get("field")) or {}
            cols.append({
                "fieldname": c.get("field"),
                "label": c.get("label") or src.get("label") or c.get("field"),
                "align": c.get("align") or src.get("align") or "left",
                "width": c.get("width"),
            })
    else:
        cols = [{"fieldname": c.get("fieldname"), "label": c.get("label") or c.get("fieldname"),
                 "align": c.get("align") or "left", "width": None} for c in all_cols]
    if not cols:
        return ""
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    hc = navy if s.get("headerColor") == "navy" else primary
    sk = _tbl_skin(s, b, hc)
    hs_size = _num((s.get("headerStyle") or {}).get("size")) if isinstance(s.get("headerStyle"), dict) else None
    th_extra = ("" if hs_size else "font-size:7.5pt;") + (sk["pad"] or "padding:6px 8px;") + sk["td_border"]
    colgroup = "<colgroup>" + "".join(
        (f'<col style="width:{_fmt_num(c.get("width"))}mm">' if c.get("width") else "<col>") for c in cols
    ) + "</colgroup>"
    heads = "".join(
        f'<th style="{sk["th"]}{"color:#fff !important;" if "color:" not in sk["th"] else ""}'
        f'text-align:{(c.get("align") or "left")};font-weight:600;{th_extra}'
        f'word-wrap:break-word;-webkit-print-color-adjust:exact;">'
        f'{_esc(c.get("label") or c.get("fieldname"))}</th>'
        for c in cols
    )
    if sk["th_first"]:
        heads = heads.replace('style="', 'style="' + sk["th_first"], 1)
        k = heads.rfind('style="')
        heads = heads[:k] + 'style="' + sk["th_last"] + heads[k + 7:]
    body = []
    for row in rows:
        tds = ""
        for c in cols:
            val = row.get(c.get("fieldname")) if hasattr(row, "get") else ""
            val = "" if val is None else str(val)
            align = c.get("align") or "left"
            td_pad = sk["pad"] or "padding:6px 8px;"
            td_bor = sk["td_border"] or "border-bottom:1px solid #cfe5f6;"
            td_num = sk["num"] if align == "right" else ""
            tds += (f'<td style="text-align:{align};{td_pad}{td_bor}{td_num}'
                    f'word-wrap:break-word;"><bdi>{_esc(val)}</bdi></td>')
        body.append(f"<tr>{tds}</tr>")
    zcls, zbg = _zebra_parts(s)
    if zbg:
        body = [(f'<tr style="{zbg}">' + r[4:]) if (i % 2 == 1) else r for i, r in enumerate(body)]
    return f'<table class="{zcls}" style="{sk["table"]}">{colgroup}<thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table>'


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
    cols = max(1, min(4, int(_num(s.get("cols"), 2) or 2)))
    gap = max(0.0, _num(s.get("gap"), 6) or 0)
    pct = max(20.0, min(100.0, _num(s.get("width"), 100) or 100))
    widths = _list(s.get("widths"))
    cells = _list(s.get("cells"))
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
    return f'<table style="width:{_fmt_num(pct)}%;border-collapse:collapse;table-layout:fixed;"><tr>{"".join(tds)}</tr></table>'


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
    "report_title": _d_report_title,
    "report_filters": _d_report_filters,
    "report_table": _d_report_table,
    "report_native": _d_report_native,
}


def _branding_from_def(definition, doc):
    from brandpdf import resolver
    b = resolver.resolve_branding(doc)
    dbr = definition.get("branding") or {}
    if _hexok(dbr.get("primary")):
        b["primary"] = dbr["primary"].strip()
    if _hexok(dbr.get("navy")):
        b["navy"] = dbr["navy"].strip()
    for k in ("header_image", "footer_image"):
        v = dbr.get(k)
        if v == "none":  # explicit per-format opt-out of the company (Settings) banner
            b[k] = ""
        elif v:
            b[k] = v
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
        if dbr.get(k) and dbr[k] != "none":  # "none" = banner opt-out sentinel, not a path
            srcs.add(dbr[k])
    for bl in definition.get("blocks") or []:
        if bl.get("type") == "image":
            src = (bl.get("settings") or {}).get("src")
            if src:
                srcs.add(src)
    return srcs


def collect_doc_image_srcs(doc, definition):
    """DOC-derived image srcs the render will emit (unknown at definition time): the items rows'
    own `image` attachments, when an items block has showImage on. These join the inline_images
    allow-list; path-traversal is still blocked downstream by assets._safe_local_path."""
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            return set()
    if not isinstance(definition, dict):
        return set()

    def _wants_images(blocks_list):
        for bl in blocks_list or []:
            if not isinstance(bl, dict):
                continue
            if bl.get("type") == "items" and (bl.get("settings") or {}).get("showImage"):
                return True
            if bl.get("type") == "row":
                for cell in (bl.get("settings") or {}).get("cells") or []:
                    if isinstance(cell, list) and _wants_images(cell):
                        return True
        return False

    if not _wants_images(definition.get("blocks")):
        return set()
    srcs = set()
    try:
        for it in (doc.get("items") or []):
            src = it.get("image")
            if src and (str(src).startswith("/files/") or str(src).startswith("/private/files/")):
                srcs.add(src)
    except Exception:
        pass
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
    _pw, _ph = page_dims(definition)
    parts = [base_css(branding, _pw, _ph)]
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


def _absolute_page_html(doc, branding, blocks_list, ctx, grow=False, top_mm=0.0, bottom_mm=0.0, y_shift=0.0, pw=210.0, ph=297.0):
    """Render blocks absolutely positioned on the page (A4 portrait or landscape via pw/ph).
    grow=True -> page may flow onto multiple pages (min-height, no clipping).
    top_mm/bottom_mm reserve @page margins so a flowing body stays clear of the running header/
    footer bands on EVERY page; y_shift offsets each block's top so page-1 positions stay correct
    once a top margin is reserved."""
    font = branding.get("font") or "Montserrat"
    navy = branding.get("navy", "#1A1E2A")
    parts = [base_css(branding, pw, ph)]
    parts.append(_pf_css(top_mm or 0, bottom_mm or 0, pw=pw, ph=ph))  # host-parsed margin contract (0 = full-bleed overlays)
    if top_mm or bottom_mm:
        parts.append(f"<style>@page{{margin:{_fmt_num(top_mm)}mm 0mm {_fmt_num(bottom_mm)}mm 0mm;}}</style>")
    if grow:
        container = "position:relative;width:%smm;min-height:%smm;" % (_fmt_num(pw), _fmt_num(max(20, ph - top_mm - bottom_mm)))
    else:
        container = "position:relative;width:%smm;height:%smm;overflow:hidden;" % (_fmt_num(pw), _fmt_num(ph))
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


_SPLITTABLE = {"items", "datatable", "table", "payment_schedule",
               "report_table", "report_native"}


def _flow_body_html(doc, branding, body_blocks, ctx, top_mm=0.0, bottom_mm=0.0, floats=None, spacer_mode=False, pw=210.0, ph=297.0):
    """Body in document flow: blocks stack top-to-bottom (so a variable-length items table never
    overlaps the totals/terms below it), reserving @page top/bottom margins so the body stays
    clear of the running header/footer bands on EVERY page. `floats` are free-positioned elements
    placed absolutely (page coords) within the body — for logos/stamps/signatures/notes.

    spacer_mode=True is the fallback for PDF engines that honor NEITHER @page CSS margins NOR
    explicit margin options (compose probes this once): the page prints full-bleed and the band
    clearance comes from a wrapper table whose repeating <thead>/<tfoot> hold invisible spacers —
    table header/footer groups repeat on every printed page in Chromium and wkhtmltopdf alike."""
    font = branding.get("font") or "Montserrat"
    navy = branding.get("navy", "#1A1E2A")
    parts = [base_css(branding, pw, ph)]
    if spacer_mode:
        parts.append(f"<style>@page{{size:{_fmt_num(pw)}mm {_fmt_num(ph)}mm;margin:0mm;}}</style>")
        parts.append(_pf_css(0, 0, pw=pw, ph=ph))
    else:
        parts.append(f"<style>@page{{size:{_fmt_num(pw)}mm {_fmt_num(ph)}mm;margin:{_fmt_num(top_mm)}mm 0mm {_fmt_num(bottom_mm)}mm 0mm;}}</style>")
        parts.append(_pf_css(top_mm, bottom_mm, pw=pw, ph=ph))
    parts.append(
        # box-sizing MATTERS: without it this box is 210mm + 28mm padding = 238mm — Chromium
        # silently shrink-to-fits (~0.88x, shrinking fonts with it) and wkhtmltopdf CLIPS the
        # right column off the page. border-box keeps 210mm meaning 210mm.
        f'<div style="position:relative;width:{_fmt_num(pw)}mm;box-sizing:border-box;padding:0 14mm;font-family:\'{font}\',\'Segoe UI\',Arial,sans-serif;'
        f'color:{navy};font-size:8.5pt;-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
    )
    if spacer_mode:
        parts.append(
            '<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr><td style="border:0;padding:0;"><div style="height:{_fmt_num(top_mm)}mm;"></div></td></tr></thead>'
            f'<tfoot><tr><td style="border:0;padding:0;"><div style="height:{_fmt_num(bottom_mm)}mm;"></div></td></tr></tfoot>'
            '<tbody><tr><td style="border:0;padding:0;">'
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
        # Only long, row-based blocks may straddle a page break (they paginate at their own rows).
        # Everything else prints whole or moves to the next page — matching the builder's canvas,
        # where the same rule decides where a page is cut.
        brk = "" if t in _SPLITTABLE else "page-break-inside:avoid;break-inside:avoid;"
        parts.append(f'<div style="margin-bottom:4mm;{brk}{css}">{inner}</div>')
    if spacer_mode:
        parts.append("</td></tr></tbody></table>")
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
        # page coord -> container coord: with @page margins the container starts at the top
        # margin; in spacer_mode the container starts at the page top (margins are spacers).
        y = _num(pos.get("y"), 0) - (0 if spacer_mode else top_mm)
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
    pw, ph = page_dims(definition)
    return _absolute_page_html(doc, branding, blocks_list, ctx, grow=False, pw=pw, ph=ph)


def watermark_page_html(branding, wm, pw=210.0, ph=297.0):
    """A full A4 page containing just a big rotated, semi-transparent watermark — merged BEHIND
    every page by compose. Empty string if no watermark text."""
    if not isinstance(wm, dict) or not wm.get("text"):
        return ""
    color = wm["color"].strip() if _hexok(wm.get("color")) else "#1A1E2A"
    op = _num(wm.get("opacity"), 8) or 8
    size = _num(wm.get("size"), 60) or 60
    angle = _num(wm.get("angle"), -35)
    font = branding.get("font") or "Montserrat"
    # Centering via absolute 50%/50% + translate (NOT flex): wkhtmltopdf's QtWebKit has no
    # display:flex, but it does support (-webkit-)transform — works on every generator.
    xf = f"translate(-50%,-50%) rotate({_fmt_num(angle)}deg)"
    return (
        base_css(branding, pw, ph)
        + _pf_css(0, 0, pw=pw, ph=ph)
        + f"<div style=\"position:relative;width:{_fmt_num(pw)}mm;height:{_fmt_num(ph)}mm;overflow:hidden;font-family:'{font}',Arial,sans-serif;\">"
        + f'<div style="position:absolute;top:50%;left:50%;-webkit-transform:{xf};transform:{xf};'
        + f'font-size:{_fmt_num(size)}pt;font-weight:800;'
        + f'color:{color};opacity:{_fmt_num((op or 8) / 100.0)};white-space:nowrap;letter-spacing:2px;'
        + f'-webkit-print-color-adjust:exact;print-color-adjust:exact;">{_esc(wm.get("text"))}</div></div>'
    )
