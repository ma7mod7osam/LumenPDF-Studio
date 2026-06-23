"""Primary engine: in-process headless Chromium via Playwright.

Runs ONLY inside the background 'long' queue worker (a fresh browser is launched per render
for leak-safety; PLAN H2 — persistent-browser pooling is a later optimization). Two fixes
from code review: the font-readiness gate now actually AWAITS document.fonts.ready (B3), and
the configured render timeout is applied to set_content/pdf (H3).
"""
from brandpdf.render.base import BaseRenderer
from brandpdf.config import conf


class PlaywrightRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        from playwright.sync_api import sync_playwright

        options = options or {}
        timeout_ms = int((conf("render_timeout") or 120) * 1000)
        launch = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        exe = conf("chromium_path")
        if exe:
            launch["executable_path"] = exe

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.set_content(html, wait_until="load", timeout=timeout_ms)
                # Actually await the font promise (B3) — otherwise the gate is a no-op and
                # Arabic can render in a fallback face.
                try:
                    page.evaluate("async () => { if (document.fonts) { await document.fonts.ready; } }")
                except Exception:
                    pass
                return page.pdf(
                    format=options.get("format", "A4"),
                    print_background=options.get("print_background", True),
                    prefer_css_page_size=options.get("prefer_css_page_size", True),
                    display_header_footer=options.get("display_header_footer", False),
                    header_template=options.get("header_template", "<span></span>"),
                    footer_template=options.get("footer_template", "<span></span>"),
                    margin=options.get("margin", {"top": "0", "bottom": "0", "left": "0", "right": "0"}),
                )
            finally:
                browser.close()
