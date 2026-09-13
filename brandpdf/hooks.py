app_name = "brandpdf"  # internal module id — DO NOT rename (breaks imports/hooks/DocType module)
app_title = "LumenPDF Studio"
app_publisher = "Lumen Solutions (BSTC W.L.L)"
app_description = ("Visual print-format builder for Frappe/ERPNext: design pixel-perfect branded "
                   "PDFs for documents AND reports with drag-and-drop blocks, ready-made templates, "
                   "multi-company branding and bilingual (EN/AR) support.")
app_email = "support@bstc-bh.com"
app_license = "MIT"
app_logo_url = "/assets/brandpdf/images/lumenpdf-logo.svg"

# ---------------------------------------------------------------------------
# Client: a global script adds the "Download Branded PDF" button to every DocType
# that has an enabled BrandPDF Mapping (Phase 2); with no mappings it falls back to
# Quotation. See public/js/brandpdf_button.js.
# ---------------------------------------------------------------------------
app_include_js = [
    "/assets/brandpdf/js/brandpdf_button.js",
    # "Branded PDF" button in the Query Report view. A .bundle.js: bench build gives it a
    # content-hashed URL every deploy, so browsers can never serve a stale copy of it.
    "brandpdf_report_button.bundle.js",
]

# Standard BrandPDF templates are read-only (duplicate to edit).
# '*'.on_submit: auto-attach the branded PDF when the mapping's toggle is on (cheap no-op otherwise).
doc_events = {
    "BrandPDF Template": {
        "validate": "brandpdf.resolver.protect_standard_template",
    },
    "*": {
        "on_submit": "brandpdf.overrides.auto_attach_on_submit",
    },
}

# Replace ERPNext's native Print > PDF with the branded PDF for doctypes whose BrandPDF Mapping
# has 'Replace Print > PDF' enabled; everything else falls through to the native renderer.
override_whitelisted_methods = {
    "frappe.utils.print_format.download_pdf": "brandpdf.overrides.download_pdf",
    # Wrap the native Report > PDF in the branded header/footer when Settings.brand_reports is on.
    "frappe.utils.print_format.report_to_pdf": "brandpdf.report.report_to_pdf",
}

# Scheduler: clean up expired private render files.
scheduler_events = {
    "daily": [
        "brandpdf.pdf_job.cleanup_expired_files",
    ],
}

# After every deploy/migrate: (1) create/upgrade the BrandPDF config DocTypes (the format
# builder screens) as Custom DocTypes — no command needed; (2) make sure a Chromium is
# available for the Playwright engine. Both idempotent + non-fatal.
after_migrate = [
    "brandpdf.setup.install_config.ensure_config",
    "brandpdf.compose.clear_probe_cache",  # engine behavior may change with a deploy
]
