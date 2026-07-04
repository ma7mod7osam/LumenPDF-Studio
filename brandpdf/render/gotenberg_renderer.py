"""Fallback/Phase-2 engine: a Gotenberg container (Chromium HTML->PDF over HTTP).

Same options, different transport. Selected via site_config `brandpdf_engine: "gotenberg"`.
Assets MUST already be inlined (base64) by the caller, since Gotenberg renders standalone.
Margin values are passed through with their unit (Gotenberg v8 parses "0"/"36mm"); M4.
"""
from brandpdf.render.base import BaseRenderer
from brandpdf.config import conf


class GotenbergRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        import requests

        options = options or {}
        base = (conf("render_url") or "http://localhost:3000").rstrip("/")
        url = base + "/forms/chromium/convert/html"
        margin = options.get("margin", {})
        # Gotenberg requires the HTML part to be named index.html.
        files = {"files": ("index.html", html, "text/html")}
        data = {
            "printBackground": "true",
            "preferCssPageSize": "true" if options.get("prefer_css_page_size", True) else "false",
            "marginTop": str(margin.get("top", "0")),
            "marginBottom": str(margin.get("bottom", "0")),
            "marginLeft": str(margin.get("left", "0")),
            "marginRight": str(margin.get("right", "0")),
        }
        # preferCssPageSize=true already makes @page CSS drive the size (incl. landscape); pass
        # explicit dims too (Gotenberg wants inches) so it's correct even if that flag is off.
        pw, ph = options.get("page_width_mm"), options.get("page_height_mm")
        if pw and ph:
            data["paperWidth"] = f"{float(pw) / 25.4:.3f}"
            data["paperHeight"] = f"{float(ph) / 25.4:.3f}"
        resp = requests.post(url, files=files, data=data, timeout=conf("render_timeout") or 120)
        resp.raise_for_status()
        return resp.content
