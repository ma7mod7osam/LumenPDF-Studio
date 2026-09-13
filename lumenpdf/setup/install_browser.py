# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Make Chromium available to the renderer on a managed host (Frappe Cloud), self-healing.

Only needed for the OPT-IN playwright engine (the default frappe_chrome engine reuses the host's
own PDF generator). It no longer runs on migrate and never spawns processes: it only SEARCHES
the box for an existing Chromium and writes its path to site_config as `lumenpdf_chromium_path`.
Always writes a summary to Error Log (title "LumenPDF: Chromium setup"). Non-fatal.

Manual run: bench --site <site> execute lumenpdf.setup.install_browser.ensure_chromium
"""
import glob
import os

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

    # Discover an existing Chromium and point the opt-in playwright engine at it. and point the app at it (if not already configured)
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
