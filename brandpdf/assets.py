"""Inline local image assets as base64 so the renderer needs no network access.

Security (code review H4): only `src`s in the caller's `allowed` set are inlined, and the
disk path is confined (realpath) to the site's files dir — so document-supplied <img> tags
can't exfiltrate arbitrary local files (e.g. site_config.json) into the PDF.
"""
import base64
import mimetypes
import os
import re
from urllib.parse import urlparse

import frappe

_SRC_RE = re.compile(r'src=["\']([^"\']+)["\']')


def inline_images(html: str, allowed=None) -> str:
    allowed = set(allowed or [])

    def repl(m):
        url = m.group(1)
        if url.startswith("data:"):
            return m.group(0)
        path_part = urlparse(url).path
        # Allowlist: inline only explicitly permitted sources (by full url or by path).
        if allowed and url not in allowed and path_part not in allowed:
            return m.group(0)
        disk = _safe_local_path(path_part)
        if not disk or not os.path.exists(disk):
            return m.group(0)
        mime = mimetypes.guess_type(disk)[0] or "image/png"
        # Safe by construction: `disk` comes from _safe_local_path(), which realpath-confines it to
        # this site's files directories, and only allow-listed srcs reach this point.
        with open(disk, "rb") as fh:  # nosemgrep
            b64 = base64.b64encode(fh.read()).decode()
        return f'src="data:{mime};base64,{b64}"'

    return _SRC_RE.sub(repl, html)


# --- block server-side fetches at render time (SSRF defense, engine-agnostic) -------------
# Legitimate images are already base64-inlined by inline_images(); anything still remote is
# either an attacker URL (e.g. http://169.254.169.254/...) or a missing file. Strip those, plus
# external CSS url()/@import, EXCEPT an allow-list of font CDNs. Defends even engines we can't
# network-isolate (frappe_chrome / Gotenberg).
_ALLOW_FETCH_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_IMG_SRC = re.compile(r"""src=["']([^"']*)["']""", re.I)
_AT_IMPORT = re.compile(r"""@import\s+url\(\s*["']?([^"')]+)["']?\s*\)\s*;?""", re.I)
_CSS_URL = re.compile(r"""url\(\s*["']?\s*(https?:[^)"']+)["']?\s*\)""", re.I)


def _host_allowed(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _ALLOW_FETCH_HOSTS)


def neutralize_remote(html: str) -> str:
    def _img(m):
        tag = m.group(0)
        sm = _IMG_SRC.search(tag)
        src = sm.group(1) if sm else ""
        return tag if (src.startswith("data:") or _host_allowed(src)) else ""

    html = _IMG_TAG.sub(_img, html)
    html = _AT_IMPORT.sub(lambda m: m.group(0) if _host_allowed(m.group(1)) else "", html)
    html = _CSS_URL.sub(lambda m: m.group(0) if _host_allowed(m.group(1)) else "url(about:blank)", html)
    return html


def _safe_local_path(path: str):
    """Map a /files/.. or /private/files/.. path to disk, confined to the files dir."""
    if "/private/files/" in path:
        rel = path.split("/private/files/", 1)[1]
        root = os.path.realpath(frappe.get_site_path("private", "files"))
    elif "/files/" in path:
        rel = path.split("/files/", 1)[1]
        root = os.path.realpath(frappe.get_site_path("public", "files"))
    else:
        return None
    candidate = os.path.realpath(os.path.join(root, rel))
    if not (candidate == root or candidate.startswith(root + os.sep)):
        return None  # path traversal attempt
    return candidate
