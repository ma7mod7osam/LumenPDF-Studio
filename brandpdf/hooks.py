app_name = "brandpdf"
app_title = "BrandPDF"
app_publisher = "BSTC"
app_description = "Pixel-perfect branded PDFs for ERPNext via a real Chromium engine."
app_email = "support@bstc-bh.com"
app_license = "MIT"

# ---------------------------------------------------------------------------
# Client: a global script adds the "Download Branded PDF" button to every DocType
# that has an enabled BrandPDF Mapping (Phase 2); with no mappings it falls back to
# Quotation. See public/js/brandpdf_button.js.
# ---------------------------------------------------------------------------
app_include_js = "/assets/brandpdf/js/brandpdf_button.js"

# Standard BrandPDF templates are read-only (duplicate to edit).
doc_events = {
    "BrandPDF Template": {
        "validate": "brandpdf.resolver.protect_standard_template",
    },
}

# Scheduler: clean up expired private render files.
scheduler_events = {
    "daily": [
        "brandpdf.pdf_job.cleanup_expired_files",
    ],
}
