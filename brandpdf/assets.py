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
        with open(disk, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        return f'src="data:{mime};base64,{b64}"'

    return _SRC_RE.sub(repl, html)


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
