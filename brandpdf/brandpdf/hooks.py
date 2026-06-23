app_name = "brandpdf"
app_title = "BrandPDF"
app_publisher = "BSTC"
app_description = "Pixel-perfect branded PDFs for ERPNext via a real Chromium engine."
app_email = "support@bstc-bh.com"
app_license = "MIT"

# ---------------------------------------------------------------------------
# Client: inject the "Download Branded PDF" button on enabled DocTypes.
# Phase 1 ships Quotation; add more here (or drive from BrandPDF Mapping in Phase 2).
# ---------------------------------------------------------------------------
doctype_js = {
    "Quotation": "public/js/brandpdf_button.js",
}

# Scheduler: clean up expired private render files (Phase 1 keeps it simple/no-op safe).
scheduler_events = {
    "daily": [
        "brandpdf.pdf_job.cleanup_expired_files",
    ],
}
