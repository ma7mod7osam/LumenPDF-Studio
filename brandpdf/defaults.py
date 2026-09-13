# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Leaf module: shared Phase-1 fallback constants.

Has NO imports from sibling brandpdf modules, so render_html and resolver can both import
these without any import-cycle risk (review #9).
"""

# DocType -> app-relative Jinja template path (last-resort fallback when a doctype has no
# BrandPDF Mapping at all; fresh installs get a block-based starter mapping instead).
TEMPLATE_MAP = {
    "Quotation": "templates/brandpdf/quotation_bstc.html",
}

# Branding fallback when a company has NO BrandPDF Settings row. Deliberately neutral:
# banner images and RTL are per-site choices — set them in BrandPDF Settings (per company)
# or per format in the builder, never hardcoded here.
DEFAULT_BRANDING = {
    "primary": "#1C75BC",
    "navy": "#1A1E2A",
    "header_image": "",
    "footer_image": "",
    "rtl": False,
}
