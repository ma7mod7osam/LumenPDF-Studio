"""Site-level configuration with safe defaults. Override in site_config.json."""
import frappe

DEFAULTS = {
    # frappe_chrome = reuse the HOST's own PDF pipeline (always present on any Frappe site; the
    # engine self-probe adapts to whatever generator is active). This makes a fresh install work
    # with ZERO site_config keys — playwright/gotenberg are opt-in overrides for advanced setups.
    "engine": "frappe_chrome",                   # "frappe_chrome" | "playwright" | "gotenberg"
    "chromium_path": None,                       # explicit chromium binary for Playwright (optional)
    "render_url": "http://localhost:3000",       # Gotenberg base URL
    "page_format": "A4",
    "render_timeout": 120,                        # seconds, background job
}


def conf(key):
    """Read lumenpdf_<key> from site_config.json, falling back to DEFAULTS."""
    val = frappe.conf.get(f"lumenpdf_{key}")
    return DEFAULTS.get(key) if val is None else val
