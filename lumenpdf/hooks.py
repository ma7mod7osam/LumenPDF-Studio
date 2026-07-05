app_name = "lumenpdf"  # internal module id — DO NOT rename (breaks imports/hooks/DocType module)
app_title = "LumenPDF Studio"
app_publisher = "BSTC"
app_description = "Pixel-perfect branded PDFs for ERPNext via a real Chromium engine."
app_email = "support@bstc-bh.com"
app_license = "MIT"

# ---------------------------------------------------------------------------
# Client: a global script adds the "Download Branded PDF" button to every DocType
# that has an enabled LumenPDF Mapping (Phase 2); with no mappings it falls back to
# Quotation. See public/js/lumenpdf_button.js.
# ---------------------------------------------------------------------------
app_include_js = "/assets/lumenpdf/js/lumenpdf_button.js"

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
after_migrate = [
    "lumenpdf.setup.install_config.ensure_config",
    "lumenpdf.setup.install_browser.ensure_chromium",
    "lumenpdf.compose.clear_probe_cache",  # engine behavior may change with a deploy
]
