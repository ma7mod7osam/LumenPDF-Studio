# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Read a format and say what will go wrong when it prints.

Every rule here exists because the defect it describes reached a real page. The one that
started it: a row carrying widths written for the default margins, left on a format whose side
margins were later narrowed, so the row stopped 18.6mm short of the right edge while the tables
around it filled the page. Nothing errored, nothing logged, it just looked wrong, and the only
way anyone found it was by looking at the paper.

The checks are pure reading. No render, no bench state, no extra dependency, so CI can run them
on every push and the builder can run them on a format before it is saved.
"""

import json

import frappe

from lumenpdf import blocks as B

# the page the format says it prints on, so a width check means something
FIT_TOLERANCE = 2.0  # mm. Below this a gap is a rounding artifact, above it is visible on paper.


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _page(definition):
    page = definition.get("page") if isinstance(definition.get("page"), dict) else {}
    pw, ph = B.page_dims(definition)
    margin_x = _num(page.get("margin_x"), 14.0)
    return pw, ph, margin_x


def check_definition(definition):
    """A list of {level, where, message}. level is 'error' for something that will print wrong,
    'warning' for something that will probably surprise, 'info' for a note."""
    if isinstance(definition, str):
        definition = json.loads(definition or "{}")
    if not isinstance(definition, dict):
        return [{"level": "error", "where": "format", "message": "The format is not readable."}]

    out = []
    pw, ph, margin_x = _page(definition)
    body_w = pw - 2 * margin_x
    blocks = definition.get("blocks") if isinstance(definition.get("blocks"), list) else []

    def where(i, bl):
        return f"block {i + 1} ({bl.get('type') or 'unknown'})"

    for i, bl in enumerate(blocks):
        if not isinstance(bl, dict):
            continue
        settings = bl.get("settings") if isinstance(bl.get("settings"), dict) else {}
        style = bl.get("style") if isinstance(bl.get("style"), dict) else {}
        pos = bl.get("pos") if isinstance(bl.get("pos"), dict) else {}

        # 1) a row of fixed columns that no longer matches the page it sits on
        if bl.get("type") == "row":
            cols = int(_num(settings.get("cols"), 2) or 2)
            gap = _num(settings.get("gap"), 6) or 0
            pct = _num(settings.get("width"), 100) or 100
            widths = settings.get("widths") if isinstance(settings.get("widths"), list) else []
            fixed = [_num(w) for w in widths[:cols]]
            if fixed and all(w for w in fixed) and len(fixed) == cols:
                total = sum(fixed) + gap * (cols - 1)
                want = body_w * pct / 100.0
                if total > want + FIT_TOLERANCE:
                    out.append({"level": "error", "where": where(i, bl),
                                "message": f"The columns add up to {total:.1f}mm but the row has "
                                           f"{want:.1f}mm, so the last one is cut off. Clear a width to let it fit."})
                elif total < want - FIT_TOLERANCE:
                    out.append({"level": "warning", "where": where(i, bl),
                                "message": f"The columns add up to {total:.1f}mm inside a {want:.1f}mm row, so it "
                                           f"stops {want - total:.1f}mm short of the margin. Clear a width to fill it."})

        # 2) a block placed past the edge of the paper
        x, w = _num(pos.get("x"), 0) or 0, _num(pos.get("w"), 0) or 0
        if w and x + w > pw + 0.5:
            out.append({"level": "error", "where": where(i, bl),
                        "message": f"This block ends at {x + w:.1f}mm on a {pw:.0f}mm page, so it prints off the edge."})
        y, h = _num(pos.get("y"), 0) or 0, _num(pos.get("h"))
        if h and y + h > ph * 20:
            out.append({"level": "warning", "where": where(i, bl),
                        "message": "This block is placed a very long way down the page."})

        # 3) a font nothing can resolve
        for key in ("font", "fontAr"):
            fam = style.get(key)
            if fam and fam not in B._FONTS:
                out.append({"level": "error", "where": where(i, bl),
                            "message": f"The font '{fam}' is not one this app can print. Pick one from the list."})

        # 4) raw HTML cannot be edited block by block
        if bl.get("type") == "box" and (settings.get("html") or "").strip():
            out.append({"level": "info", "where": where(i, bl),
                        "message": "This is hand written HTML, so the builder cannot edit its parts. "
                                   "A row with column styling usually replaces it."})

        # 5) an image the printer will not be able to fetch
        src = str(settings.get("src") or "")
        if src and not (src.startswith("/files/") or src.startswith("/private/files/")
                        or src.startswith("data:image/") or src in ("", "none")):
            out.append({"level": "error", "where": where(i, bl),
                        "message": "The image is not a file uploaded to this site, so it will not print."})

    branding = definition.get("branding") if isinstance(definition.get("branding"), dict) else {}
    for key in ("font", "font_ar"):
        fam = branding.get(key)
        if fam and fam not in B._FONTS:
            out.append({"level": "error", "where": "branding",
                        "message": f"The document font '{fam}' is not one this app can print."})
    if branding.get("font") and branding["font"] in B._FONTS and not branding.get("font_ar"):
        out.append({"level": "info", "where": "branding",
                    "message": "No Arabic font is set, so Arabic text uses the default one."})
    return out


@frappe.whitelist()
def lint_format(name: str):
    """Check one saved format."""
    if not frappe.db.exists("LumenPDF Template", name):
        frappe.throw("Unknown format.")
    definition = frappe.db.get_value("LumenPDF Template", name, "definition")
    if not definition:
        return []
    return check_definition(definition)


def check_all(strict=False):
    """Every saved format on this site. CI calls it with strict, so a format that would print
    wrong fails the build instead of reaching a release."""
    if not frappe.db.exists("DocType", "LumenPDF Template"):
        print("LumenPDF lint: no formats on this site.")
        return
    bad = 0
    for name in frappe.get_all("LumenPDF Template", pluck="name"):
        definition = frappe.db.get_value("LumenPDF Template", name, "definition")
        if not definition:
            continue
        issues = [i for i in check_definition(definition) if i["level"] != "info"]
        for issue in issues:
            print(f"  [{issue['level']}] {name} / {issue['where']}: {issue['message']}")
        bad += sum(1 for i in issues if i["level"] == "error")
    print(f"LumenPDF lint: {bad} error(s).")
    if strict and bad:
        raise RuntimeError(f"LumenPDF lint found {bad} error(s).")


def check_print_pipeline():
    """The fonts must survive Frappe's own preprocessing, not only our renderer.

    Frappe's get_pdf runs scrub_urls, which appends " !important" after every ":url(...)". Inside
    @font-face that is invalid CSS: the engine drops the face and the whole page prints in the
    host's DejaVu Sans with no error anywhere. It went unnoticed for a release because every test
    rendered our HTML directly. This runs the real scrub_urls of the bench it is on, so CI checks
    it on each Frappe version the app supports."""
    from frappe.utils.pdf import scrub_urls

    css = B.font_faces_css(["Almarai", "IBM Plex Mono"])
    if "@font-face" not in css:
        raise RuntimeError("LumenPDF: no bundled font faces were produced.")
    out = scrub_urls(css)
    broken = [chunk[:80] for chunk in out.split("@font-face")[1:] if "!important" in chunk.split("format(")[0]]
    if broken:
        raise RuntimeError("LumenPDF: Frappe's url rewrite corrupts the font faces: " + "; ".join(broken))
    print(f"LumenPDF print pipeline: {css.count('@font-face')} font faces survive Frappe's url rewrite.")
