"""Ensure Playwright's Chromium (and the headless-shell it launches) are present.

Wired to `after_migrate` so a Frappe Cloud deploy self-installs the browser without SSH.
Idempotent and non-fatal. It ALWAYS writes the result to the Error Log (title starts with
"BrandPDF: Chromium install") so you can see exactly what happened on a managed host.

Manual run: bench --site <site> execute brandpdf.setup.install_browser.ensure_chromium
"""
import subprocess
import sys

import frappe

# Recent Playwright launches headless via a separate "chromium-headless-shell" build,
# which is what the launch error asks for. Install both, each separately so one bad
# target name on an older Playwright doesn't abort the other.
_TARGETS = ("chromium", "chromium-headless-shell")


def ensure_chromium():
    log = []
    for target in _TARGETS:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "playwright", "install", target],
                check=False, timeout=900, capture_output=True, text=True,
            )
            tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-1500:]
            log.append(f"== {target} (rc={r.returncode}) ==\n{tail or '(no output)'}")
        except Exception as e:
            log.append(f"== {target} CRASHED ==\n{e}")
    frappe.log_error(title="BrandPDF: Chromium install result", message="\n\n".join(log))
