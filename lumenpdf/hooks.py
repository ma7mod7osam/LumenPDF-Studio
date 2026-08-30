# Internal module id. NEVER rename this on a site that already has the app installed: Frappe
# registers the app by this id, so renamed code + an old registration = ModuleNotFoundError that
# wedges every bench command. A rename is only safe as a FRESH install of the new id
# (uninstall old → install new), which is exactly how this branch came to exist.
app_name = "lumenpdf"
app_title = "LumenPDF Studio"
app_publisher = "Lumen Solutions (BSTC W.L.L)"
app_description = ("Visual print-format builder for Frappe/ERPNext: design pixel-perfect branded "
                   "PDFs for documents AND reports with drag-and-drop blocks, ready-made templates, "
                   "multi-company branding and bilingual (EN/AR) support.")
app_email = "support@bstc-bh.com"
app_license = "MIT"
app_logo_url = "/assets/lumenpdf/images/lumenpdf-logo.svg"

# ---------------------------------------------------------------------------
# Client: a global script adds the "Download Branded PDF" button to every DocType
# that has an enabled LumenPDF Mapping (Phase 2); with no mappings it falls back to
# Quotation. See public/js/lumenpdf_button.js.
# ---------------------------------------------------------------------------
app_include_js = [
    "/assets/lumenpdf/js/lumenpdf_button.js",
    # "Branded PDF" button in the Query Report view. A .bundle.js: bench build gives it a
    # content-hashed URL every deploy, so browsers can never serve a stale copy of it.
    "lumenpdf_report_button.bundle.js",
]

# Standard LumenPDF templates are read-only (duplicate to edit).
# '*'.on_submit: auto-attach the branded PDF when the mapping's toggle is on (cheap no-op otherwise).
doc_events = {
    "LumenPDF Template": {
        "validate": "lumenpdf.resolver.protect_standard_template",
    },
    "*": {
        "on_submit": "lumenpdf.overrides.auto_attach_on_submit",
    },
}

# Replace ERPNext's native Print > PDF with the branded PDF for doctypes whose LumenPDF Mapping
# has 'Replace Print > PDF' enabled; everything else falls through to the native renderer.
override_whitelisted_methods = {
    "frappe.utils.print_format.download_pdf": "lumenpdf.overrides.download_pdf",
    # Wrap the native Report > PDF in the branded header/footer when Settings.brand_reports is on.
    "frappe.utils.print_format.report_to_pdf": "lumenpdf.report.report_to_pdf",
}

# Scheduler: clean up expired private render files.
scheduler_events = {
    "daily": [
        "lumenpdf.pdf_job.cleanup_expired_files",
    ],
}

# After every deploy/migrate: (1) create/upgrade the LumenPDF config DocTypes (the format
# builder screens) as Custom DocTypes — no command needed; (2) make sure a Chromium is
# available for the Playwright engine. Both idempotent + non-fatal.
# Fresh install: after_migrate does NOT fire on `install-app`, so the config DocTypes would
# never be created and the builder would 500 with TableMissingError. ensure_config is idempotent,
# so running it here AND on every migrate is safe.
after_install = "lumenpdf.setup.install_config.ensure_config"

after_migrate = [
    "lumenpdf.setup.install_config.ensure_config",
    "lumenpdf.setup.install_browser.ensure_chromium",
    "lumenpdf.compose.clear_probe_cache",  # engine behavior may change with a deploy
]
