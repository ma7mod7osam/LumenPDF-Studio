"""Make Chromium available to the renderer on a managed host (Frappe Cloud), self-healing.

Runs on `after_migrate`. Strategy:
  1. Try to download Playwright's own Chromium + headless-shell (works on hosts with egress).
  2. If that didn't yield a usable binary, SEARCH the box for any existing Chromium (Frappe
     Cloud ships one for its own chrome PDF) and write its path to site_config as
     `lumenpdf_chromium_path`, which the renderer launches via executable_path.
Always writes a summary to Error Log (title "LumenPDF: Chromium setup"). Non-fatal.

Manual run: bench --site <site> execute lumenpdf.setup.install_browser.ensure_chromium
"""
import glob
import os
import subprocess
import sys

import frappe

_SEARCH = [
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "/home/frappe/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "/home/frappe/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
]


def ensure_chromium():
    log = []

    # 1. attempt download (no-op/fast if already present; fails quietly if egress is blocked)
    for target in ("chromium", "chromium-headless-shell"):
        try:
            r = subprocess.run(
                [sys.executable, "-m", "playwright", "install", target],
                check=False, timeout=900, capture_output=True, text=True,
            )
            log.append(f"install {target}: rc={r.returncode} {((r.stdout or '') + (r.stderr or '')).strip()[-400:]}")
        except Exception as e:
            log.append(f"install {target}: crashed {e}")

    # 2. find an existing Chromium and point the app at it (if not already configured)
    if not frappe.conf.get("lumenpdf_chromium_path"):
        found = []
        for pat in _SEARCH:
            found += [p for p in glob.glob(os.path.expanduser(pat)) if os.path.exists(p)]
        log.append("existing binaries: " + (", ".join(found) if found else "NONE"))
        if found:
            try:
                from frappe.installer import update_site_config
                update_site_config("lumenpdf_chromium_path", found[0])
                log.append("=> set lumenpdf_chromium_path = " + found[0])
            except Exception as e:
                log.append("could not write site_config: " + str(e))
    else:
        log.append("lumenpdf_chromium_path already set: " + str(frappe.conf.get("lumenpdf_chromium_path")))

    frappe.log_error(title="LumenPDF: Chromium setup", message="\n".join(log)[:9000])
