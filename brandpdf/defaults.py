"""Leaf module: shared Phase-1 fallback constants.

Has NO imports from sibling brandpdf modules, so render_html and resolver can both import
these without any import-cycle risk (review #9).
"""

# DocType -> app-relative Jinja template path.
TEMPLATE_MAP = {
    "Quotation": "templates/brandpdf/quotation_bstc.html",
}

# Per-company branding fallback (resolver overrides via BrandPDF Settings).
DEFAULT_BRANDING = {
    "primary": "#1C75BC",
    "navy": "#1A1E2A",
    "header_image": "/files/2Header.png",
    "footer_image": "/files/2Footer.png",
    "rtl": True,
}
