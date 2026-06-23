"""Site-level configuration with safe defaults. Override in site_config.json."""
import frappe

DEFAULTS = {
    "engine": "playwright",                     # "playwright" | "gotenberg"
    "chromium_path": None,                       # explicit chromium binary for Playwright (optional)
    "render_url": "http://localhost:3000",       # Gotenberg base URL
    "page_format": "A4",
    "render_timeout": 120,                        # seconds, background job
}


def conf(key):
    """Read brandpdf_<key> from site_config.json, falling back to DEFAULTS."""
    val = frappe.conf.get(f"brandpdf_{key}")
    return DEFAULTS.get(key) if val is None else val
