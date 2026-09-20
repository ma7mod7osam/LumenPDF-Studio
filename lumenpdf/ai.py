# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.

"""Design copilot: plain-language instructions -> a validated format definition.

The model never renders anything and never touches the database. It only ever produces the SAME
definition JSON the visual builder produces, and every answer is put through `sanitize_definition`
before it reaches the canvas: unknown block types, unknown keys, bad colours, out-of-range numbers
and oversized payloads are dropped. So the worst a confused (or hostile) answer can do is make an
ugly format the user can undo.

Bring-your-own-key: the Gemini key lives in LumenPDF Settings (encrypted) or in site_config.
"""

import json

import frappe
import requests
from frappe import _

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# floating alias: Google keeps it pointed at the current flash model
DEFAULT_MODEL = "gemini-flash-latest"
# Google retires dated model names and keeps the "-latest" aliases pointed at the current ones,
# so the alias leads and the dated names are only a fallback for keys that pin an older model.
ALTERNATE_MODELS = ("gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash")
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 90
MAX_BLOCKS = 80
MAX_INSTRUCTION = 4000
# A reference document the model LOOKS at (screenshot, scan or PDF). Gemini reads these natively.
ATTACH_MIMES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif", "application/pdf"}
MAX_ATTACH_BYTES = 12 * 1024 * 1024

BLOCK_TYPES = {
    "header_banner", "footer_banner", "title", "customer", "items", "datatable", "row", "totals",
    "payment_schedule", "terms", "signature", "heading", "text", "field", "image", "divider",
    "box", "table", "pagenum", "qr", "spacer", "report_title", "report_filters", "report_table",
}
ROW_CHILD_TYPES = BLOCK_TYPES - {"row", "header_banner", "footer_banner"}
STYLE_KEYS = {"align", "size", "weight", "italic", "underline", "color", "bg", "pad", "mt", "mb",
              "width", "font", "letterSpacing", "lineHeight", "rtl", "border"}
BORDER_KEYS = {"on", "w", "color", "style", "radius", "sides"}
PAGE_KEYS = {"orientation", "bg", "margin_x"}
REGIONS = {"body", "header", "footer"}


# --------------------------------------------------------------------------------------------
# key + settings
# --------------------------------------------------------------------------------------------
def _settings():
    """The site-wide copilot settings (a Single DocType created by setup.install_config)."""
    try:
        return frappe.get_single("LumenPDF AI Settings")
    except Exception:
        return None


def _resolve_key():
    doc = _settings()
    if doc:
        try:
            key = doc.get_password("gemini_api_key", raise_exception=False)
        except Exception:
            key = None
        if key:
            return key
    return frappe.conf.get("lumenpdf_gemini_key") or frappe.conf.get("lumenpdf_gemini_key") or ""


def _model():
    doc = _settings()
    return (doc and doc.get("gemini_model")) or DEFAULT_MODEL


def _scrub(text, key):
    text = str(text or "")
    return text.replace(key, "***") if key else text


@frappe.whitelist()
def ai_status():
    """Does the copilot have what it needs, and may this user change it?"""
    from lumenpdf.api import _require_manager

    _require_manager()
    return {
        "ready": bool(_resolve_key()),
        "model": _model(),
        "can_set_key": bool(frappe.has_permission("LumenPDF AI Settings", "write")),
        "key_source": "site_config" if frappe.conf.get("lumenpdf_gemini_key") else "settings",
    }


@frappe.whitelist()
def save_ai_key(api_key=None, model=None):
    """Store the key encrypted on LumenPDF Settings. Never echoed back."""
    from lumenpdf.api import _require_manager

    _require_manager()
    doc = _settings()
    if not doc:
        frappe.throw(_("LumenPDF AI Settings is not installed yet. Run a migrate and try again."))
    if api_key is not None:
        doc.gemini_api_key = (api_key or "").strip()
    if model:
        doc.gemini_model = model.strip()
    doc.flags.ignore_permissions = False
    doc.save()
    return ai_status()


@frappe.whitelist()
def list_models():
    """The text models this key may call, newest-looking first. Lets the copilot offer a real
    choice instead of guessing a name Google may have retired."""
    from lumenpdf.api import _require_manager

    _require_manager()
    key = _resolve_key()
    if not key:
        return []
    skip = ("embedding", "aqa", "image", "tts", "audio", "vision-", "learnlm", "gemma")
    try:
        r = requests.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=30)
        if r.status_code != 200:
            return []
        out = []
        for m in r.json().get("models") or []:
            name = str(m.get("name") or "").replace("models/", "")
            if not name or any(t in name for t in skip):
                continue
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            out.append(name)
        out.sort(key=lambda n: ("latest" not in n, n), reverse=False)
        return out[:40]
    except requests.RequestException:
        return []


# --------------------------------------------------------------------------------------------
# the briefing: everything the model needs to write a format this app can actually render
# --------------------------------------------------------------------------------------------
SCHEMA_BRIEF = """
You design print formats for LumenPDF Studio, a block-based print-format builder for Frappe/ERPNext.
You return ONE JSON object: a complete format DEFINITION. No prose, no markdown, no code fences.

DEFINITION SHAPE
{
  "name": "<short format name>",
  "layout": "absolute",
  "target_doctype": "<the doctype this format prints>",
  "target_kind": "doctype",
  "page": {"orientation": "portrait"|"landscape", "bg": "#RRGGBB" (optional page colour),
           "margin_x": <side margin mm, default 14; 4-6 for edge-to-edge bands>},
  "header": {"enabled": bool, "height": <mm>, "repeat": bool, "margin": <mm gap below>},
  "footer": {"enabled": bool, "height": <mm>, "repeat": bool, "margin": <mm gap above>},
  "watermark": {"text": "", "color": "#RRGGBB", "opacity": 8, "size": 60},
  "branding": {"primary": "#RRGGBB", "navy": "#RRGGBB", "font": "<font name>",
               "header_image": "", "footer_image": ""},
  "blocks": [ <block>, ... ]
}

BLOCK SHAPE
{"type": "<type>", "region": "body"|"header"|"footer", "float": false, "cond": null,
 "pos": {"x": <mm>, "y": <mm>, "w": <mm>, "h": null}, "settings": {...}, "style": {...}}

LAYOUT RULES (important)
- Body blocks FLOW top to bottom in ascending pos.y. pos.x and pos.w are ignored in the body flow,
  so use pos.y ONLY to order blocks, and control width with style.width ("60%") or a row.
- Blocks are 14mm from each paper edge by default (page.margin_x changes that).
- Every block gets 4mm bottom spacing; style.mt / style.mb add or remove millimetres.
- float: true pins a block to page coordinates (pos.x/y/w) and draws it ON TOP of the flow. Use it
  only for stamps/logos; never for the main content.
- header/footer blocks live in their bands (region + enabled + height).
- "cond": {"field": "<fieldname>", "op": "="|"!="|">"|"<"|">="|"<="|"like"|"in", "value": "<v>"}
  hides the block unless the document matches. Use it for payment-type or status variants.

STYLE KEYS (all optional)
align: left|center|right · size: pt · weight: "400".."800" · italic/underline: bool · color/bg: #hex
pad/mt/mb: mm · width: "70%" · font: one of the font list · letterSpacing: px · lineHeight: number
rtl: true (right-to-left text) · border: {"on":true,"w":1,"color":"#hex","style":"solid|dashed|dotted",
"radius":px,"sides":{"t":bool,"r":bool,"b":bool,"l":bool}}

BLOCK TYPES AND THEIR settings
- heading / text: {"text": "..."} — a real newline inside text prints as a line break.
- field: {"field": "<fieldname or link_field.target_field>", "prefix": "", "html": true|false}
  html:true renders a field that already contains HTML (address_display, terms).
- image: {"src": "/files/...", "width": <percent>}
- divider: {"thickness": 1, "color": "#hex", "lstyle": "solid|dashed|dotted"}
- box: {"html": "<b>Note</b><br>free HTML, sanitized"} — LAST RESORT. A box cannot be edited block
  by block in the builder, so reach for a row with cellStyles, a table, or a divider first.
- spacer: {} with style.pad for vertical space.
- pagenum: {"format": "Page {p} of {n}"}
- qr: {"mode": "zatca"|"field"|"text", "field": "name", "text": "", "size": <mm>, "ecc": "L|M|Q|H"}
  zatca builds the Saudi tax-invoice payload from the document itself.
- row: {"cols": 2|3|4, "gap": <mm>, "width": 100, "widths": [<mm>|null, ...],
        "cells": [[<child block>, ...], ...],
        "cellStyles": [{"bg":"#hex","padX":<mm>,"padY":<mm>,"align":"left|center|right",
                        "valign":"top|middle|bottom","radius":px,
                        "border":{"on":true,"w":1,"color":"#hex","style":"solid",
                                  "sides":{"t":false,"r":true,"b":false,"l":false}}}, ...]}
  Children are blocks WITHOUT pos/region; this is how you place things side by side. Cells may hold
  text, field, heading, image, divider, box, qr, table, datatable, totals, customer, signature.
  cellStyles paints ONE column: a coloured header card, a tinted sidebar, or a hairline between two
  columns (border with only one side on). Use it instead of writing an HTML box.
- table (static): {"cols": ["Col A","Col B"], "rows": [["a","b"], ...], "headerBg": "#hex",
   "headerOn": false, "colStyle": [{"w":<mm>,"align","size","weight","color","bg","bw","bcolor","bstyle"}],
   "rowStyle": [{"bg":"#hex","color":"#hex","size":pt,"weight":"700","h":<mm>}],
   "borders": {...}, "cellPad": {"y":px,"x":px}, "zebra": bool, "zebraColor": "#hex"}
  A cell whose whole text is "{fieldname}" prints that document field. A cell may contain a newline
  to print two lines. "headerOn": false drops the header band, so row 1 becomes the first visible
  line — that is how a label/value panel or a banded summary strip is built.
- items (the ready item table): {"cols": {"desc":true,"qty":true,"rate":true,"amount":true},
   "widths": {"num":8,"item":100,"qty":16,"rate":28,"amount":30}, "zebra": bool,
   "headerColor": "primary"|"navy", "showImage": bool, "imgPos": "top|left|right", "imgW": mm,
   "imgH": mm, "labels": {"num":"#","item":"...","qty":"...","rate":"...","amount":"..."},
   "headerStyle": {"bg":"#hex","color":"#hex","size":pt,"weight":"600","radius":px},
   "borders": {"preset":"grid|rows|outline|none","w":1,"color":"#hex","style":"solid"},
   "cellPad": {"y":px,"x":px}, "colStyles": {"num|item|qty|rate|amount": {"color","size","weight","align"}},
   "descStyle": {"color","size"}}
- datatable (ANY child table): {"table": "<child table fieldname>", "child_doctype": "...",
   "columns": [{"label": "...", "width": <mm|null>, "align": "left|center|right",
                "lines": [{"field": "...", "size": pt, "color": "#hex", "weight": "700",
                           "italic": bool, "upper": bool}, ...]}],
   plus the same headerStyle / borders / cellPad / zebra / headerColor keys as items.
   Each column is a STACK of lines, which is how you print a name over its description.
- totals: {"subtotalLabel","discountLabel","grandLabel","grandColor":"primary|navy","grandBg",
   "grandTextColor","grandSize","labelColor","valueColor","valueSize","width": <mm>}
- customer: {"heading","headingColor","nameColor","nameSize","addrColor","addrSize"}
- title: {"text","showArabic","arabic","meta":{"name":true,"date":true,"valid_till":true},
   "align":"split|center","titleColor","titleSize","metaLabels":{...},"metaLabelColor",
   "metaValueColor","metaBorderColor"}
- terms: {"heading"} · payment_schedule: {"heading","headerColor"} ·
  signature: {"label","boxW","lineW","lineColor","labelColor","labelSize"}
- header_banner / footer_banner: {} — they print the company banner image from Settings.

BILINGUAL WORK
- A table column label may contain a newline: "الوصف\\nDESCRIPTION" stacks Arabic over English.
  The same works for totals labels.
- Put style.rtl true on Arabic text/field blocks, and align them "right".
- Arabic-capable fonts: Cairo, Almarai, Tajawal, IBM Plex Sans Arabic, Noto Kufi Arabic, Amiri.
- Latin fonts: Plus Jakarta Sans, Inter, Montserrat, Roboto, Open Sans, Lato, Poppins, Archivo,
  Manrope, Bricolage Grotesque, Newsreader, Instrument Serif, IBM Plex Mono, Arial, Tahoma.

RULES
- Use ONLY the block types, settings keys and style keys listed above. Anything else is dropped.
- Bind real data with field/datatable/items/totals blocks and the fieldnames given below. Never
  invent fieldnames, and never hard-code a customer's data as static text.
- Colours are #RRGGBB. Sizes are numbers (pt for text, mm for layout).
- Keep it under 60 blocks and keep the JSON valid.
"""


IMITATE_GUIDE = """
A REFERENCE DOCUMENT IS ATTACHED (image or PDF). Study it before writing anything:
1. Page: A4 portrait or landscape? Is the paper tinted (page.bg)? How far is the content from the
   left/right paper edge, in mm (page.margin_x)? Measure against the 210mm A4 width.
2. Palette: read the real colours off the page as #RRGGBB: bands, table headers, rules, text,
   tinted rows. Set branding.primary to the dominant accent and branding.navy to the body text.
3. Type: pick the closest font from the allowed list (Arabic-capable fonts for Arabic text) and
   estimate each text size in pt from its height relative to the page.
4. Structure, top to bottom: bands/cards, title lockup, meta rows, party blocks, item table,
   totals, payment/bank details, terms, signature, footer, QR. Reproduce each one with the
   closest blocks: rows for side-by-side areas, datatable for line items (a column label may
   stack Arabic over English with a newline), totals for the money summary, qr for a QR code.
5. Bind every value that changes per document to a real field of the target doctype. Keep the
   printed LABELS from the reference (translated only if the user asks). Replace the sender's
   name, logo, address, VAT and CR numbers with fields or neutral placeholders.
6. Spacing: copy the rhythm. Use style.mt/mb and cellPad so gaps match the reference.
Return the full definition.
"""


def _clean_attachment(att):
    """Validate an uploaded reference file: an allow-listed type, base64, and a size cap."""
    import base64

    if not att:
        return None
    if isinstance(att, str):
        try:
            att = json.loads(att)
        except ValueError:
            return None
    if not isinstance(att, dict):
        return None
    mime = str(att.get("mime") or "").lower().strip()
    data = str(att.get("data") or "")
    if "," in data[:80] and data.startswith("data:"):
        data = data.split(",", 1)[1]  # tolerate a data: URL
    if mime not in ATTACH_MIMES or not data:
        frappe.throw(_("Attach a PNG, JPG, WEBP or PDF file."))
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        frappe.throw(_("The attached file could not be read."))
    if len(raw) > MAX_ATTACH_BYTES:
        frappe.throw(_("The attached file is too large. Keep it under 12 MB."))
    if mime == "application/pdf" and not raw.startswith(b"%PDF"):
        frappe.throw(_("That file is not a real PDF."))
    return {"mime_type": mime, "data": data}


def _fields_brief(doctype):
    """The fieldnames the model may bind to, plus the child tables it can build datatables from."""
    if not doctype or not frappe.db.exists("DocType", doctype):
        return ""
    meta = frappe.get_meta(doctype)
    skip = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"}
    fields, tables = [], []
    for df in meta.fields:
        if not df.fieldname or (df.permlevel or 0) != 0:
            continue
        if df.fieldtype in ("Table", "Table MultiSelect"):
            tables.append((df.fieldname, df.options))
            continue
        if df.fieldtype in skip:
            continue
        fields.append(f"{df.fieldname} ({df.label or df.fieldname})")
    out = [f"TARGET DOCTYPE: {doctype}", "FIELDS: name, " + ", ".join(fields[:120])]
    for fieldname, child in tables[:6]:
        try:
            cmeta = frappe.get_meta(child)
            cf = [f.fieldname for f in cmeta.fields
                  if f.fieldname and (f.permlevel or 0) == 0
                  and f.fieldtype not in skip and f.fieldtype not in ("Table", "Table MultiSelect")]
        except Exception:
            cf = []
        out.append(f"CHILD TABLE '{fieldname}' ({child}) FIELDS: idx, " + ", ".join(cf[:40]))
    return "\n".join(out)


def _prompt(mode, instruction, definition, doctype, sample, attached=False):
    parts = [SCHEMA_BRIEF, _fields_brief(doctype)]
    if mode == "edit":
        parts.append("TASK: change the format below as asked. Keep everything the user did not ask "
                     "to change, including block order, colours and bindings. Return the FULL "
                     "definition, not a patch.")
        parts.append("CURRENT DEFINITION:\n" + json.dumps(definition, ensure_ascii=False)[:120000])
    elif mode == "clone":
        parts.append("TASK: build a NEW format that reproduces the design described or supplied "
                     "below, as closely as the block vocabulary allows, bound to the target "
                     "doctype's own fields. Do not copy any company name, logo, address or tax "
                     "number from the sample: keep it generic.")
        if attached:
            parts.append(IMITATE_GUIDE)
        if sample:
            parts.append("SAMPLE TO IMITATE:\n" + str(sample)[:120000])
        if definition:
            parts.append("THE USER'S CURRENT FORMAT (for palette/context only):\n"
                         + json.dumps(definition, ensure_ascii=False)[:40000])
    else:
        parts.append("TASK: design a new format from scratch for this document.")
    if attached and mode != "clone":
        parts.append("An image or PDF of a reference document is attached. Use it as the visual "
                     "reference for what the user asks.")
    parts.append("USER REQUEST:\n" + str(instruction or "")[:MAX_INSTRUCTION])
    parts.append("Return only the JSON object.")
    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------------------------
# validation: nothing the model returns is trusted
# --------------------------------------------------------------------------------------------
def _hex(v):
    v = str(v or "").strip()
    return v if (len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])) else None


def _number(v, lo, hi, default=None):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clean_style(style):
    if not isinstance(style, dict):
        return {}
    out = {}
    for k, v in style.items():
        if k not in STYLE_KEYS:
            continue
        if k in ("color", "bg"):
            c = _hex(v)
            if c:
                out[k] = c
        elif k in ("size", "pad", "mt", "mb", "letterSpacing", "lineHeight"):
            # per-key ranges: a 400pt "font size" is a broken page, not a bold choice
            lo, hi = {"size": (1, 120), "pad": (0, 120), "mt": (-100, 200), "mb": (-100, 200),
                      "letterSpacing": (-10, 30), "lineHeight": (0.5, 4)}[k]
            n = _number(v, lo, hi)
            if n is not None:
                out[k] = n
        elif k == "border" and isinstance(v, dict):
            b = {bk: bv for bk, bv in v.items() if bk in BORDER_KEYS}
            if _hex(b.get("color")):
                b["color"] = _hex(b["color"])
            else:
                b.pop("color", None)
            b["w"] = _number(b.get("w"), 0, 20, 1)
            b["radius"] = _number(b.get("radius"), 0, 60, 0)
            if isinstance(b.get("sides"), dict):
                b["sides"] = {s: bool(b["sides"].get(s, True)) for s in ("t", "r", "b", "l")}
            out["border"] = b
        elif k in ("italic", "underline", "rtl"):
            out[k] = bool(v)
        else:
            out[k] = str(v)[:40]
    return out


def _clean_settings(settings):
    """Settings are per-type and deeply nested; keep the shape, drop anything that isn't JSON-safe
    and cap the sizes that could blow up a page."""
    if not isinstance(settings, dict):
        return {}
    def walk(v, depth=0):
        if depth > 6:
            return None
        if isinstance(v, dict):
            return {str(k)[:40]: walk(x, depth + 1) for k, x in list(v.items())[:60]}
        if isinstance(v, list):
            return [walk(x, depth + 1) for x in v[:200]]
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            return v
        return str(v)[:8000]
    return walk(settings) or {}


def _clean_block(b, allow_children=True):
    if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
        return None
    t = b["type"]
    pos = b.get("pos") if isinstance(b.get("pos"), dict) else {}
    out = {
        "type": t,
        "region": b.get("region") if b.get("region") in REGIONS else "body",
        "float": bool(b.get("float")),
        "cond": b.get("cond") if isinstance(b.get("cond"), dict) and b["cond"].get("field") else None,
        "pos": {"x": _number(pos.get("x"), 0, 600, 14), "y": _number(pos.get("y"), 0, 2000, 0),
                "w": _number(pos.get("w"), 5, 600, 182), "h": _number(pos.get("h"), 0, 2000)},
        "settings": _clean_settings(b.get("settings")),
        "style": _clean_style(b.get("style")),
    }
    if b.get("hidden"):
        out["hidden"] = True
    if b.get("locked"):
        out["locked"] = True
    if t == "row" and allow_children:
        cells = out["settings"].get("cells")
        clean_cells = []
        for cell in (cells if isinstance(cells, list) else [])[:4]:
            kids = []
            for child in (cell if isinstance(cell, list) else [])[:20]:
                if isinstance(child, dict) and child.get("type") in ROW_CHILD_TYPES:
                    c = _clean_block(child, allow_children=False)
                    if c:
                        kids.append({"type": c["type"], "settings": c["settings"], "style": c["style"]})
            clean_cells.append(kids)
        out["settings"]["cells"] = clean_cells or [[], []]
        out["settings"]["cols"] = int(_number(out["settings"].get("cols"), 1, 4, len(clean_cells) or 2))
    return out


def sanitize_definition(d, fallback_doctype=None):
    """Turn whatever the model produced into a definition this app can render, or raise."""
    if isinstance(d, str):
        d = json.loads(d)
    if not isinstance(d, dict) or not isinstance(d.get("blocks"), list):
        frappe.throw(_("The AI did not return a usable format. Try rephrasing the request."))
    page = d.get("page") if isinstance(d.get("page"), dict) else {}
    clean_page = {"orientation": "landscape" if str(page.get("orientation")) == "landscape" else "portrait"}
    if _hex(page.get("bg")):
        clean_page["bg"] = _hex(page["bg"])
    mx = _number(page.get("margin_x"), 0, 90)
    if mx is not None:
        clean_page["margin_x"] = mx

    def band(key, default_h):
        z = d.get(key) if isinstance(d.get(key), dict) else {}
        return {"enabled": bool(z.get("enabled")), "height": _number(z.get("height"), 0, 200, default_h),
                "repeat": bool(z.get("repeat", True)), "margin": _number(z.get("margin"), 0, 60, 4)}

    br = d.get("branding") if isinstance(d.get("branding"), dict) else {}
    branding = {"primary": _hex(br.get("primary")) or "#1463FF", "navy": _hex(br.get("navy")) or "#0C1322",
                "font": str(br.get("font") or "Plus Jakarta Sans")[:40],
                "header_image": str(br.get("header_image") or "")[:255],
                "footer_image": str(br.get("footer_image") or "")[:255]}
    wm = d.get("watermark") if isinstance(d.get("watermark"), dict) else {}
    watermark = {"text": str(wm.get("text") or "")[:120], "color": _hex(wm.get("color")) or "#0C1322",
                 "opacity": _number(wm.get("opacity"), 0, 100, 8), "size": _number(wm.get("size"), 6, 200, 60)}

    blocks = []
    for b in d["blocks"][:MAX_BLOCKS]:
        c = _clean_block(b)
        if c:
            blocks.append(c)
    if not blocks:
        frappe.throw(_("The AI returned a format with no usable blocks. Try rephrasing the request."))
    return {
        "name": str(d.get("name") or "AI format")[:140],
        "layout": "absolute",
        "target_doctype": str(d.get("target_doctype") or fallback_doctype or "")[:140],
        "target_kind": "doctype",
        "report_name": "",
        "page": clean_page,
        "header": band("header", 30),
        "footer": band("footer", 32),
        "watermark": watermark,
        "branding": branding,
        "blocks": blocks,
    }


# --------------------------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------------------------
def _generate(prompt, key, model, attachment=None):
    parts = [{"text": prompt}]
    if attachment:
        # the reference goes first, so the model reads the picture before the instructions
        parts.insert(0, {"inline_data": attachment})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25}}
    last_error = None
    tried = []
    for candidate in [model] + [m for m in ALTERNATE_MODELS if m != model]:
        try:
            r = requests.post(GEMINI_URL.format(model=candidate), headers={"x-goog-api-key": key},
                              json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            frappe.throw(_("Could not reach the Gemini API: {0}").format(_scrub(e, key)))
        if r.status_code == 200:
            try:
                return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            except Exception:
                frappe.throw(_("The AI returned an unreadable answer. Try rephrasing the request."))
        detail = ""
        try:
            detail = _scrub(r.json().get("error", {}).get("message", "")[:200], key)
        except Exception:
            pass
        if r.status_code in (400, 401, 403) and "key" in detail.lower():
            frappe.throw(_("The Gemini API key was rejected. Check it in LumenPDF AI Settings."))
        # 404 means Google retired that model name for this key, which is exactly what the next
        # candidate is for. 429/500/503 are busy or out of quota. Both step sideways.
        if r.status_code in (404, 429, 500, 503):
            last_error = detail or r.status_code
            tried.append(candidate)
            continue
        frappe.throw(_("Gemini API error {0}: {1}").format(r.status_code, detail))
    frappe.throw(_("None of these models answered: {0}. Last message from Google: {1}. "
                   "Pick a model your key supports in LumenPDF AI Settings.").format(", ".join(tried), last_error))


@frappe.whitelist()
def ai_format(instruction, definition=None, mode="edit", target_doctype=None, sample=None, attachment=None):
    """Design or change a format from a plain-language instruction. Returns a sanitized definition."""
    from lumenpdf.api import _require_manager

    _require_manager()
    key = _resolve_key()
    if not key:
        frappe.throw(_("Add a Gemini API key in LumenPDF AI Settings to use the design copilot."))
    att = _clean_attachment(attachment)
    if not (instruction or "").strip():
        if not att:
            frappe.throw(_("Tell the copilot what to design or change."))
        instruction = "Reproduce the attached document's design for this doctype."
    if isinstance(definition, str) and definition.strip():
        try:
            definition = json.loads(definition)
        except ValueError:
            definition = None
    mode = mode if mode in ("edit", "create", "clone") else "edit"
    doctype = target_doctype or (definition or {}).get("target_doctype") or "Quotation"
    out = _generate(_prompt(mode, instruction, definition, doctype, sample, attached=bool(att)),
                    key, _model(), attachment=att)
    return {"definition": sanitize_definition(out, fallback_doctype=doctype),
            "notes": str(out.get("notes") or "")[:500] if isinstance(out, dict) else ""}
