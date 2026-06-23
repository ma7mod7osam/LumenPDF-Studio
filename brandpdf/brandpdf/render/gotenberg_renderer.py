"""Fallback/Phase-2 engine: a Gotenberg container (Chromium HTML->PDF over HTTP).

Same options, different transport. Selected via site_config `brandpdf_engine: "gotenberg"`.
Assets MUST already be inlined (base64) by the caller, since Gotenberg renders standalone.
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
        files = {"files": ("index.html", html, "text/html")}
        data = {
            "printBackground": "true",
            "preferCssPageSize": "true" if options.get("prefer_css_page_size", True) else "false",
            "marginTop": _mm(margin.get("top", "0")),
            "marginBottom": _mm(margin.get("bottom", "0")),
            "marginLeft": _mm(margin.get("left", "0")),
            "marginRight": _mm(margin.get("right", "0")),
        }
        resp = requests.post(url, files=files, data=data, timeout=conf("render_timeout") or 120)
        resp.raise_for_status()
        return resp.content


def _mm(v):
    """Gotenberg wants margins in inches; accept '0'/'36mm' and convert."""
    s = str(v).strip().lower()
    if s.endswith("mm"):
        return str(round(float(s[:-2]) / 25.4, 3))
    if s.endswith("in"):
        return s[:-2]
    return s  # bare number treated as inches by Gotenberg
