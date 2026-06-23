"""Primary engine: in-process headless Chromium via Playwright.

Runs ONLY inside the background 'long' queue worker (never the web process) so a single
Chromium is launched per render and memory stays bounded (PLAN H7). The font-readiness
gate (document.fonts.ready) removes the top cause of blurry/fallback fonts (PLAN H5).
"""
from brandpdf.render.base import BaseRenderer
from brandpdf.config import conf


class PlaywrightRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        from playwright.sync_api import sync_playwright

        options = options or {}
        launch = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        exe = conf("chromium_path")
        if exe:
            launch["executable_path"] = exe

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            try:
                page = browser.new_page()
                # 'load' (not 'networkidle') + explicit font gate is the correct readiness signal.
                page.set_content(html, wait_until="load")
                try:
                    page.evaluate("document.fonts && document.fonts.ready")
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
