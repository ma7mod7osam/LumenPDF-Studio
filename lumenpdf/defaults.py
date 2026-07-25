"""Leaf module: shared Phase-1 fallback constants.

Has NO imports from sibling lumenpdf modules, so render_html and resolver can both import
these without any import-cycle risk (review #9).
"""

# DocType -> app-relative Jinja template path (last-resort fallback when a doctype has no
# LumenPDF Mapping at all; fresh installs get a block-based starter mapping instead).
TEMPLATE_MAP = {
    "Quotation": "templates/lumenpdf/quotation_bstc.html",
}

# Branding fallback when a company has NO LumenPDF Settings row. Deliberately neutral:
# banner images and RTL are per-site choices — set them in LumenPDF Settings (per company)
# or per format in the builder, never hardcoded here.
DEFAULT_BRANDING = {
    "primary": "#1C75BC",
    "navy": "#1A1E2A",
    "header_image": "",
    "footer_image": "",
    "rtl": False,
}
