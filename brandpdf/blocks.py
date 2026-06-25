"""Block engine — assemble a print format from an ordered list of blocks.

A "format" is just blocks: header_banner, title, customer, items, totals,
payment_schedule, terms, signature, footer_banner, spacer, custom_html.
`render_blocks(doc, branding, rows, terms_html)` turns that list into the same clean,
full-bleed HTML the hand-written template produces — so non-coders compose formats by
adding/reordering block rows (Stage 1: a form; Stage 2: drag-and-drop UI on top).

Each block renderer takes (doc, branding, row, ctx) and returns an HTML fragment. `row`
is the block config (block_type, label, content). Banners render full-width; everything
else sits inside a padded content area.
"""
import frappe

CONTENT_BLOCKS_ORDER = [
    "header_banner", "title", "customer", "items", "totals",
    "payment_schedule", "terms", "signature", "footer_banner",
]

BANNER_BLOCKS = {"header_banner", "footer_banner"}


def base_css(b):
    primary = b.get("primary", "#1C75BC")
    navy = b.get("navy", "#1A1E2A")
    return f"""<style>
  @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&family=Montserrat:wght@300;400;500;600;700;800&display=swap');
  @page {{ size: A4; margin: 0; }}
  html, body {{ margin:0 !important; padding:0 !important; }}
  img {{ max-width:100%; }}
  .bs-banner {{ width:100%; display:block; }}
  .bs-content {{ font-family:'Montserrat','Segoe UI',Arial,sans-serif; color:{navy}; font-size:8.5pt; padding:6mm 14mm; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
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
        # address_display is system-generated HTML (<br> line breaks) -> render raw.
        out.append(f'<div class="addr">{addr}</div>')
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
