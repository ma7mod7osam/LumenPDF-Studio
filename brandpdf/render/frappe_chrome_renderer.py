"""Engine that reuses the HOST's own Chrome PDF pipeline.

On Frappe Cloud the platform already runs a Chromium for its native "chrome" PDF generator,
even though we can't find/launch the binary ourselves. This engine feeds OUR rendered HTML
straight into `frappe.utils.pdf.get_pdf(..., pdf_generator="chrome")`, so it reuses that
working Chromium and skips the whole "install a browser in the bench" problem.

Enable with site_config: "brandpdf_engine": "frappe_chrome".
"""
import inspect

import frappe

from brandpdf.render.base import BaseRenderer


class FrappeChromeRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        from frappe.utils.pdf import get_pdf

        params = inspect.signature(get_pdf).parameters
        call = {}

        # Force the chrome generator if this frappe version's get_pdf supports the kwarg.
        if "pdf_generator" in params:
            call["pdf_generator"] = "chrome"

        # frappe/wkhtmltopdf-style options. Harmless for chrome; aims for A4 + zero margins so
        # our @page{margin:0} + full-bleed banners are honored.
        if "options" in params:
            call["options"] = {
                "page-size": "A4",
                "margin-top": "0mm",
                "margin-bottom": "0mm",
                "margin-left": "0mm",
                "margin-right": "0mm",
                "print-media-type": True,
            }

        pdf = get_pdf(html, **call)
        if isinstance(pdf, str):
            pdf = pdf.encode("latin-1", errors="ignore")
        if not pdf:
            frappe.throw("BrandPDF (frappe_chrome): get_pdf returned empty output.")
        return pdf
