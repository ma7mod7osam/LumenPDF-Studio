# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Engine abstraction. Swapping engines is a config change, never a rewrite (PLAN 2.1)."""
from lumenpdf.config import conf


class BaseRenderer:
    def render(self, html: str, options: dict = None) -> bytes:  # noqa: D401
        raise NotImplementedError


def default_options() -> dict:
    """The exact options the stock Frappe generator hides from us (PLAN 2.2)."""
    return {
        "format": conf("page_format") or "A4",
        "print_background": True,
        "prefer_css_page_size": True,        # honor @page { margin:0 } -> true full-bleed
        "display_header_footer": False,
        "margin": {"top": "0", "bottom": "0", "left": "0", "right": "0"},
    }


def get_renderer() -> BaseRenderer:
    engine = (conf("engine") or "frappe_chrome").lower().replace("-", "_")
    if engine == "gotenberg":
        from lumenpdf.render.gotenberg_renderer import GotenbergRenderer
        return GotenbergRenderer()
    if engine == "playwright":
        from lumenpdf.render.playwright_renderer import PlaywrightRenderer
        return PlaywrightRenderer()
    # Default: reuse the host's own PDF pipeline (always present; no browser to install and the
    # engine self-probe adapts to whatever generator is active). Zero site_config required.
    from lumenpdf.render.frappe_chrome_renderer import FrappeChromeRenderer
    return FrappeChromeRenderer()
