"""Inline local image assets as base64 so the renderer needs no network access and the
HTML is portable across both engines (PLAN H10: images inline, fonts local)."""
import base64
import mimetypes
import os
import re
from urllib.parse import urlparse

import frappe

_SRC_RE = re.compile(r'src=["\']([^"\']+)["\']')


def inline_images(html: str) -> str:
    def repl(m):
        url = m.group(1)
        if url.startswith("data:"):
            return m.group(0)
        path = _local_file_path(url)
        if not path or not os.path.exists(path):
            return m.group(0)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        return f'src="data:{mime};base64,{b64}"'

    return _SRC_RE.sub(repl, html)


def _local_file_path(url: str):
    """Map a /files/.. or /private/files/.. URL (absolute or relative) to a disk path."""
    path = urlparse(url).path
    if "/private/files/" in path:
        rel = path.split("/private/files/", 1)[1]
        return frappe.get_site_path("private", "files", rel)
    if "/files/" in path:
        rel = path.split("/files/", 1)[1]
        candidate = frappe.get_site_path("public", "files", rel)
        return candidate
    return None
