"""Engine that reuses the HOST's own Chrome PDF pipeline.

On Frappe Cloud the platform already runs a Chromium for its native "chrome" PDF generator,
even though we can't find/launch the binary ourselves. This engine feeds OUR rendered HTML
straight into `frappe.utils.pdf.get_pdf(..., pdf_generator="chrome")`, so it reuses that
working Chromium and skips the whole "install a browser in the bench" problem.

Enable with site_config: "lumenpdf_engine": "frappe_chrome".
"""
import inspect

import frappe

from lumenpdf.render.base import BaseRenderer


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
            pw = (options or {}).get("page_width_mm")
            ph = (options or {}).get("page_height_mm")
            if pw and ph and float(pw) > float(ph):
                call["options"].pop("page-size", None)
                call["options"]["page-width"] = _mm(pw)
                call["options"]["page-height"] = _mm(ph)
                call["options"]["orientation"] = "Landscape"

        pdf = get_pdf(html, **call)
        if isinstance(pdf, str):
            pdf = pdf.encode("latin-1", errors="ignore")
        if not pdf:
            frappe.throw("LumenPDF (frappe_chrome): get_pdf returned empty output.")
        return pdf
