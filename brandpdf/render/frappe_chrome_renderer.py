# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Engine that reuses the HOST's own Chrome PDF pipeline.

On Frappe Cloud the platform already runs a Chromium for its native "chrome" PDF generator,
even though we can't find/launch the binary ourselves. This engine feeds OUR rendered HTML
straight into `frappe.utils.pdf.get_pdf(..., pdf_generator="chrome")`, so it reuses that
working Chromium and skips the whole "install a browser in the bench" problem.

Landscape: some hosts' chrome generators silently IGNORE the page-width/page-height/orientation
keys (observed live: landscape-positioned content on a portrait A4 page). The renderer therefore
VERIFIES the output orientation and, when the chrome generator can't turn the page, re-renders
through wkhtmltopdf (a hard Frappe dependency that honors --orientation). The verdict is cached
so the double render happens at most once a day.

Enable with site_config: "brandpdf_engine": "frappe_chrome".
"""
import inspect
import io

import frappe

from brandpdf.render.base import BaseRenderer

_LAND_CACHE = "brandpdf_chrome_landscape"  # "ok" | "broken", probed from real output


def _is_landscape_pdf(pdf: bytes) -> bool:
    try:
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader
        page = PdfReader(io.BytesIO(pdf)).pages[0]
        return float(page.mediabox.width) > float(page.mediabox.height)
    except Exception:
        return True  # can't inspect -> assume fine (never fall back on a guess)


def _land_state():
    try:
        return frappe.cache().get_value(_LAND_CACHE)
    except Exception:
        return None


def _set_land_state(v):
    try:
        frappe.cache().set_value(_LAND_CACHE, v, expires_in_sec=86400)
    except Exception:
        pass


class FrappeChromeRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        from frappe.utils.pdf import get_pdf

        params = inspect.signature(get_pdf).parameters
        call = {}

        # Force the chrome generator if this frappe version's get_pdf supports the kwarg.
        if "pdf_generator" in params:
            call["pdf_generator"] = "chrome"

        # Page margins MUST travel as explicit options: wkhtmltopdf ignores @page CSS margins,
        # and Chrome's CDP applies param margins when the CSS gives none. compose passes the
        # band clearance in options['margin']; everything else renders full-bleed (0).
        # (Engines never stack the two: Chromium lets @page CSS win, wkhtmltopdf only sees these.)
        m = (options or {}).get("margin") or {}

        def _mm(v):
            v = str(v or "0mm")
            return v if v.endswith(("mm", "cm", "in", "px")) else f"{v}mm"

        # EXACTLY this key set and nothing more: print_designer's chrome generator reads these
        # five keys; feeding it an unknown wkhtmltopdf flag (b18 added disable-smart-shrinking)
        # made it discard the whole option set and fall back to its 15mm top/bottom defaults —
        # which shifted the bands down and pushed the footer off-page. Proven-good set = b17's.
        pw = (options or {}).get("page_width_mm")
        ph = (options or {}).get("page_height_mm")
        want_landscape = bool(pw and ph and float(pw) > float(ph))
        if "options" in params:
            call["options"] = {
                "page-size": (options or {}).get("format") or "A4",
                "margin-top": _mm(m.get("top")),
                "margin-bottom": _mm(m.get("bottom")),
                "margin-left": _mm(m.get("left")),
                "margin-right": _mm(m.get("right")),
                "print-media-type": True,
            }
            # Landscape/custom size ONLY: add explicit dims (portrait keeps the proven key set
            # byte-identical — some patched generators discard options on unknown keys, and for
            # those the .print-format page-width/page-height dialect in the HTML still applies).
            if want_landscape:
                call["options"].pop("page-size", None)
                call["options"]["page-width"] = _mm(pw)
                call["options"]["page-height"] = _mm(ph)
                call["options"]["orientation"] = "Landscape"

        # Landscape hint INSIDE the html too: frappe's read_options_from_html extracts
        # orientation/page-width/page-height from .print-format styles, and some patched chrome
        # generators reuse that parser. Harmless where ignored.
        if want_landscape:
            html = ('<style>.print-format{orientation: landscape; '
                    f'page-width: {_mm(pw)}; page-height: {_mm(ph)};}}</style>') + html

        # Known-broken chrome landscape on this host -> go straight to wkhtml (no wasted render).
        if want_landscape and _land_state() == "broken":
            wk = self._wkhtml_landscape(html, m, _mm)
            if wk is not None and _is_landscape_pdf(wk):
                return wk

        pdf = get_pdf(html, **call)
        if isinstance(pdf, str):
            pdf = pdf.encode("latin-1", errors="ignore")
        if not pdf:
            frappe.throw("BrandPDF (frappe_chrome): get_pdf returned empty output.")

        # Verify landscape actually happened; some hosts' chrome generators ignore the dims.
        if want_landscape:
            if _is_landscape_pdf(pdf):
                _set_land_state("ok")
            else:
                _set_land_state("broken")
                wk = self._wkhtml_landscape(html, m, _mm)
                if wk is not None and _is_landscape_pdf(wk):
                    return wk
                try:
                    frappe.log_error(title="BrandPDF: landscape not produced by any engine",
                                     message="chrome ignored the page dims and the wkhtml fallback "
                                             "returned portrait/empty — landscape formats will clip.")
                except Exception:
                    pass
        return pdf

    def _wkhtml_landscape(self, html, m, _mm):
        """Render via wkhtmltopdf DIRECTLY (pdfkit), bypassing frappe.utils.pdf.get_pdf entirely:
        on hosts where a patched get_pdf routes every call to the site's configured 'chrome'
        generator, asking get_pdf for wkhtmltopdf just loops back to chrome (observed live —
        portrait again, no error). pdfkit.from_string cannot be redirected.
        Returns None on any failure so the caller keeps the chrome output (never worse)."""
        try:
            import re

            # Render OFFLINE: the only remote refs left after neutralize_remote are the Google
            # Fonts imports, and wkhtml can stall for minutes waiting on that fetch. Strip them —
            # fonts fall back to system faces; the layout (the reason we're here) is unaffected.
            html = re.sub(r"@import\s+url\([^)]*fonts\.googleapis[^)]*\)\s*;?", "", html)
            html = re.sub(r"<link[^>]+fonts\.(?:googleapis|gstatic)[^>]*>", "", html)

            options = {
                "page-size": "A4",
                "orientation": "Landscape",
                "margin-top": _mm(m.get("top")),
                "margin-bottom": _mm(m.get("bottom")),
                "margin-left": _mm(m.get("left")),
                "margin-right": _mm(m.get("right")),
                "print-media-type": None,
                "background": None,
                "encoding": "UTF-8",
                "quiet": None,
                # frappe's own safety flags; our html is self-contained (data: URIs, no scripts)
                "disable-javascript": "",
                "disable-local-file-access": "",
                "disable-smart-shrinking": "",  # exact mm: the body is laid out at true page width
            }
            import pdfkit

            pdf = pdfkit.from_string(html, False, options=options)
            if isinstance(pdf, str):
                pdf = pdf.encode("latin-1", errors="ignore")
            return pdf or None
        except Exception:
            try:
                frappe.log_error(title="BrandPDF wkhtml landscape fallback failed",
                                 message=frappe.get_traceback())
            except Exception:
                pass
            return None
