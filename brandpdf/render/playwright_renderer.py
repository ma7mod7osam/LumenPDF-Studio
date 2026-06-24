"""Primary engine: in-process headless Chromium via Playwright.

Managed-host hardening: at render time we look for an existing Chromium (Frappe Cloud ships
one) and launch THAT via executable_path when Playwright's own download is missing/blocked.
If no browser can be found, the raised error lists exactly what was searched/found, so the
failure in the Error Log is self-explanatory (no log-digging needed).
"""
import glob
import os
import shutil

from brandpdf.render.base import BaseRenderer
from brandpdf.config import conf

# /usr/bin/chromium-browser on Ubuntu is a snap stub, not a real binary — never use it.
_SNAP_STUB = "/usr/bin/chromium-browser"

# A real Chromium can live in many places on a managed host. Full chrome first, then the
# headless-shell, then system installs.
_GLOBS = [
    "~/.cache/ms-playwright/**/chrome-linux*/chrome",
    "/home/frappe/.cache/ms-playwright/**/chrome-linux*/chrome",
    "/ms-playwright/**/chrome-linux*/chrome",
    "/opt/**/chrome-linux*/chrome",
    "~/.cache/ms-playwright/**/chrome-headless-shell",
    "/home/frappe/.cache/ms-playwright/**/chrome-headless-shell",
    "/ms-playwright/**/chrome-headless-shell",
    "/snap/chromium/current/usr/lib/chromium-browser/chrome",
    "/usr/lib/chromium/chrome",
    "/usr/lib/chromium/chromium",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
]


def _find_chromium():
    found = []
    patterns = list(_GLOBS)
    bp = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if bp:
        patterns = [bp + "/**/chrome-linux*/chrome", bp + "/**/chrome-headless-shell"] + patterns
    for pat in patterns:
        try:
            for p in glob.glob(os.path.expanduser(pat), recursive=True):
                if os.path.isfile(p) and p != _SNAP_STUB and p not in found:
                    found.append(p)
        except Exception:
            pass
    for name in ("chromium", "google-chrome-stable", "google-chrome", "chrome"):
        w = shutil.which(name)
        if w and w != _SNAP_STUB and w not in found:
            found.append(w)
    return found


class PlaywrightRenderer(BaseRenderer):
    def render(self, html: str, options: dict = None) -> bytes:
        from playwright.sync_api import sync_playwright

        options = options or {}
        timeout_ms = int((conf("render_timeout") or 120) * 1000)

        exe = conf("chromium_path")
        candidates = _find_chromium()
        if not exe and candidates:
            exe = candidates[0]  # reuse the host's existing Chromium

        launch = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if exe:
            launch["executable_path"] = exe

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**launch)
            except Exception as e:
                raise RuntimeError(
                    "BrandPDF: could not launch Chromium. "
                    f"site_config brandpdf_chromium_path={conf('chromium_path')!r}; "
                    f"used executable_path={exe!r}; "
                    f"chromium found on disk={candidates or 'NONE'}. "
                    "If NONE, this host blocks the browser — switch to the Gotenberg engine. "
                    f"Original error: {e}"
                ) from e
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.set_content(html, wait_until="load", timeout=timeout_ms)
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
