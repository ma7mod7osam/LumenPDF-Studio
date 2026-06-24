"""Ensure Playwright's Chromium browser binary is present.

Wired to `after_migrate` so a Frappe Cloud deploy self-installs the browser without SSH.
Idempotent (playwright skips the download if already present) and non-fatal (a failure is
logged, never aborts migrate). Can also be run manually:
    bench --site <site> execute brandpdf.setup.install_browser.ensure_chromium
"""
import subprocess
import sys

import frappe


def ensure_chromium():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            timeout=900,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            frappe.log_error(
                title="BrandPDF: Chromium install non-zero exit",
                message=(result.stdout or "") + "\n" + (result.stderr or ""),
            )
        else:
            print("BrandPDF: Chromium browser ready.")
    except Exception:
        frappe.log_error(title="BrandPDF: Chromium install failed", message=frappe.get_traceback())
