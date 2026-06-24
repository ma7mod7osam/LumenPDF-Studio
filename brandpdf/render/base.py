"""Engine abstraction. Swapping engines is a config change, never a rewrite (PLAN 2.1)."""
from brandpdf.config import conf


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
    engine = (conf("engine") or "playwright").lower().replace("-", "_")
    if engine == "gotenberg":
        from brandpdf.render.gotenberg_renderer import GotenbergRenderer
        return GotenbergRenderer()
    if engine in ("frappe_chrome", "frappe"):
        # Reuse the host's own Chrome PDF pipeline (works on Frappe Cloud, no browser to install).
        from brandpdf.render.frappe_chrome_renderer import FrappeChromeRenderer
        return FrappeChromeRenderer()
    from brandpdf.render.playwright_renderer import PlaywrightRenderer
    return PlaywrightRenderer()
