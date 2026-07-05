# BrandPDF — Consolidated Fix List

Merged from 5 reviews (frappe, security, engine, template, packaging). Duplicates collapsed; items the reviewers themselves cleared (correct-as-written) are dropped.

---

## [BLOCKER]

**B1. Path-traversal + SSTI/RCE via the `template` param** — `api.py:11`, `render_html.py:27-44`, `pdf_job.py:15`
`request_pdf` whitelists a free-form `template` string that flows unvalidated into `open()` and then `frappe.render_template` (Jinja). A logged-in user can read arbitrary files (`../../../etc/passwd`, `site_config.json`) and reach server-side template injection.
**Fix:** Drop the client `template` param; resolve server-side from `TEMPLATE_MAP[doc.doctype]`. If selectable templates are needed, accept an opaque key against an allowlist (`ALLOWED_TEMPLATES = {"quotation_bstc": "templates/brandpdf/quotation_bstc.html"}`). Defensively, in `_read_template` `os.path.realpath(full)` and assert it stays within `get_app_path("brandpdf","templates")`.

**B2. `get_job_result` is unscoped — any user can read another user's PDF** — `api.py:28-30`, `pdf_job.py`
No check that the caller owns `job_id`; unguessable hash is not access control.
**Fix:** Store the owner in cached state and enforce it:
```python
def _set_state(job_id, state):
    frappe.cache().set_value(_key(job_id), {**state, "_user": frappe.session.user}, expires_in_sec=900)

@frappe.whitelist()
def get_job_result(job_id):
    state = _get_state(job_id)
    if not state: return {"status": "unknown"}
    if state.get("_user") != frappe.session.user:
        frappe.throw("Not found", frappe.PermissionError)
    return {k: v for k, v in state.items() if k != "_user"}
```
Write `_user=user` explicitly from the worker's cache writes.

**B3. `document.fonts.ready` is never awaited — the font gate is a no-op** — `playwright_renderer.py:28` (mirrored in `m0_spike.py:113`)
`page.evaluate("document.fonts && document.fonts.ready")` returns immediately; `page.pdf()` can fire before Arabic fonts load — defeating the app's core quality promise (PLAN H5). The spike has the same bug, so the gate was never actually validated.
**Fix:** `page.evaluate("async () => { if (document.fonts) { await document.fonts.ready; } }")`. Fix the spike too.

**B4. `modules.txt` declares `BrandPDF` but no matching module folder exists** — `brandpdf/brandpdf/modules.txt`
Frappe scrubs the module name to a folder and expects it to exist; `bench migrate`/`install-app`/DocType discovery break. (Reviewers split on `brandpdf` vs `brand_pdf` scrub, so do not guess — verify scrub output and make folder + modules.txt + Module Def consistent.)
**Fix:** Set `modules.txt` to `Brandpdf` and create `brandpdf/brandpdf/brandpdf/__init__.py` (or match `BrandPDF`→`brand_pdf` folder); keep all three consistent. Required before any Phase-2 DocType.

**B5. Git-root vs app-root layout breaks `bench get-app`** — repo layout, `docs/INSTALL.md`, `README.md`
`.git` is at `BrandPDF-ERPNext/` but `pyproject.toml`/`README`/`license.txt` live in `BrandPDF-ERPNext/brandpdf/`. `bench get-app` expects the app root to be a git repo.
**Fix:** Move `pyproject.toml`, `README.md`, `license.txt`, `.gitignore` up to the repo root (app root == git root), or make `brandpdf/` its own repo.

---

## [HIGH]

**H1. No concurrency-1 enforcement on the `long` queue — OOM safety is prose, not code** — `api.py:15-24`, hooks/config
PLAN H7's "single browser / Redis counter guards fan-out" is not implemented; two concurrent jobs = two Chromiums = the exact OOM the design set out to prevent (worsened by per-render launch, H2).
**Fix:** Add a Redis guard in `pdf_job.generate` (`frappe.cache().incr` a counter; bail/re-enqueue if >1, decrement in `finally`), or ship supervisor/Procfile config pinning the `long` worker to one process. The guard must be in code.

**H2. Per-render Chromium launch contradicts the documented persistent-browser model** — `playwright_renderer.py:21-22`
Code launches and closes a fresh browser every call (leak-safe, but pays cold-start each render and removes the "one browser" memory bound).
**Fix:** Implement the long-lived browser-per-worker (new `context` per render), or update the docstring/PLAN to commit to per-render launch as Phase-1 behavior.

**H3. `render_timeout` is ignored; Playwright uses its default 30s** — `playwright_renderer.py`, `config.py:9`, `api.py:16`
`set_content`/`page.pdf()` use Playwright's default 30s, so the configured 120s is silently dead; a large Arabic doc fails at 30s. Enqueue timeout (180) and render timeout (120) are also uncoordinated constants.
**Fix:** Pass `conf("render_timeout")*1000` to `set_content(..., timeout=...)` and `page.pdf(..., timeout=...)`; derive enqueue timeout as `render_timeout + 30`.

**H4. `inline_images` reads/inlines any file with no traversal guard or permission check** — `assets.py:30-40`
`/private/files/../../site_config.json` escapes the files dir; any `/private/files/<victim>` referenced in HTML is base64-embedded regardless of File read permission (confused-deputy exfil). Reachable today via unescaped `doc.terms` (H6).
**Fix:** Normalize and confine:
```python
candidate = os.path.realpath(frappe.get_site_path("private","files",rel))
root = os.path.realpath(frappe.get_site_path("private","files"))
if not candidate.startswith(root + os.sep): return None
```
(same for public branch). For private files, resolve the File doc and enforce read permission before inlining. Best for Phase 1: only inline the hardcoded branding header/footer allowlist, not arbitrary `/files` paths from document content.

**H5. `{{ frappe.utils.get_url() }}` prefix in image `src` depends on `host_name` inside the worker** — `quotation_bstc.html:55-56`, `assets.py`
The worker has no request context; `get_url()` falls back to `host_name`/site_config, frequently unset on a fresh box. Inlining handles relative `/files/...` directly, so the prefix is pointless and fragile. (Template reviewer confirmed the happy path works, but it breaks on misconfigured `host_name` — and SSRF reviewer flags it as attacker-influenceable surface.)
**Fix:** Emit plain `src="{{ branding.header_image }}"` (i.e. `/files/2Header.png`); drop `get_url()`.

**H6. `doc.terms` rendered raw — HTML-escaping bug AND injection vector** — `quotation_bstc.html:130`
Two reviewers, opposite framings, same line: `terms` is rich-text, so escaping renders literal `&lt;p&gt;` in the PDF (template reviewer wants `| safe`); but raw emit is also the delivery mechanism for the `inline_images` file-exfil/SSRF above (security reviewer wants sanitize). Resolution: it must render as HTML **and** be sanitized.
**Fix:** `{{ frappe.utils.sanitize_html(doc.terms) }}` (renders markup, strips dangerous tags). Combine with H4's `src`-prefix allowlist so document-supplied `<img>` cannot reach the file mapper.

**H7. Playwright is a hard runtime dependency, and INSTALL re-installs it manually** — `pyproject.toml`, `docs/INSTALL.md`
`playwright` is in `dependencies` yet INSTALL also tells users to `pip install playwright requests` manually — redundant and can install a resolver-mismatched version. (Chromium still needs the separate `playwright install chromium`, which is fine.)
**Fix:** Keep `playwright`/`requests` in `dependencies`; remove the manual `pip install playwright requests` line from INSTALL/README. Keep only `playwright install chromium`.

---

## [MEDIUM]

**M1. `set_user` in the worker is never reset** — `pdf_job.py:18`
RQ workers are long-lived; a leaked session means later work could run as the previous requester.
**Fix:** `prev = frappe.session.user; frappe.set_user(user); try: ... finally: frappe.set_user(prev)`.

**M2. Remote Google Fonts `@import` defeats the "no-network / fonts-local" design** — `quotation_bstc.html:10`, `assets.py`
`inline_images` only inlines `<img src>`, not `@import url(...)`, so fonts are not localized; with no worker egress the PDF silently falls back to Tahoma. Also the SSRF surface (cloud-metadata fetch) if template content becomes attacker-influenced.
**Fix:** Self-host Cairo/Montserrat as local `@font-face` (base64/bundled woff2), drop the remote `@import`. Constrain Chromium egress (no network or allowlist).

**M3. Error path swallows the real failure and mislabels permission errors** — `pdf_job.py:27-31`
Bare `except Exception` catches `frappe.PermissionError` from `check_permission("read")` and reports it as "Render failed"; `frappe.log_error(title=...)` with no message logs an empty body.
**Fix:** Do the permission check before the try (or branch on `PermissionError` with a distinct status); log with `frappe.log_error(message=frappe.get_traceback(), title="BrandPDF render failed")`.

**M4. Gotenberg margin unit conversion is unnecessary and mishandles edge cases** — `gotenberg_renderer.py:32-39`
`_mm` strips the unit and emits a bare inch number; only bites non-zero mm margins, and newer Gotenberg accepts the suffix directly. (Multipart `index.html` filename is correct — not a bug.)
**Fix:** Pass values through with their unit (`"36mm"`) and let Gotenberg parse.

**M5. No `license` field in `pyproject.toml`** — `pyproject.toml`
`hooks.py` + `license.txt` say MIT, but the wheel ships no license metadata.
**Fix:** Add `license = { file = "license.txt" }` (or `license = "MIT"` + classifier).

**M6. `pymupdf` (spike dep) is undeclared/unpinned** — `docs/INSTALL.md §0`, `m0-spike/`
Spike-only, so not in `pyproject.toml` (correct), but the ad-hoc install command is the only source of truth.
**Fix:** Add `m0-spike/requirements.txt` with `playwright` + `pymupdf` pinned; reference from INSTALL §0.

---

## [LOW]

**L1. No engine fallback despite "Playwright primary, Gotenberg fallback" goal** — `pdf_job.py:23` — `get_renderer()` is an either/or switch; if Playwright raises the job dies. Either implement try-primary-then-Gotenberg, or correct the PLAN wording to "Phase 2."

**L2. Apply field-level read permissions before render** — `pdf_job.py` / `api.py:35-42` — `get_doc` carries permlevel-restricted values (e.g. `grand_total`, `rate`) into the PDF. Call `doc.apply_fieldlevel_read_permissions()` after `check_permission`.

**L3. Item-name/desc CSS bold relies on a one-hair specificity win** — `quotation_bstc.html:43-45` — `tbody td *` neutralizer vs `.it-name` both `!important`; works only by class-count. Scope the neutralizer: `tbody td *:not(.it-name)`.

**L4. Multi-page footer/header model only pins on a single page** — `quotation_bstc.html:5-6,55-56` — `<tfoot>`/`<thead>` repeat full-bleed art on every page and body can collide with the footer (no reserved margin). Documented "v1 limit." Confirm BSTC quotations never exceed one page, else move to Playwright `headerTemplate`/`footerTemplate` with `@page` margins.

**L5. `branding.currency = "BHD"` is dead config** — `quotation_bstc.html:67-69,113-120` — `get_formatted()` uses the doc's own currency; a USD quotation renders USD. Clarify intent: enforce BHD or remove the unused key.

**L6. Enqueue timeout sourced from a hardcoded constant** — `api.py` / `config.py` — folded into H3; harmless on its own if H3 is done.

**L7. `new_page()` instead of `new_context()`** — `playwright_renderer.py:24` — harmless under per-render launch; switch to `new_context()` when adopting the persistent-browser model (H2).

---

## Dropped as fine/speculative (reviewers cleared these)
`_brandpdf` File key (frappe reviewer called it a BLOCKER, but it's a dead/no-op tag, not a crash — remove the line as cleanup, not a blocker); `frappe.cache().set_value(expires_in_sec=)` kwarg (correct in v15); `doctype_js` path (correct); `render_template` string-vs-path handling (correct); `get_app_path` join (correct — the *traversal* is the real issue, see B1); flit packaging/`dynamic=["version"]`/`bench get-app` path string (correct — the *git-root* is the real issue, see B5); flit data-file inclusion (correct); empty `__init__.py`/`patches.txt` (fine); sync-Playwright-in-RQ-worker (correct, but add a "not in web context" assert as cheap insurance); Gotenberg `index.html` filename (correct); `striptags`/`<bdi>`/`break-inside`/taxes-loop/branding-keys in the template (all correct).

---

## TOP FIXES BEFORE DEPLOY
1. **B1** — Remove/allowlist the `template` param (LFI + SSTI/RCE). Highest-impact security hole.
2. **B2** — Scope `get_job_result` to the owning user (cross-user PDF leak).
3. **B3** — Await `document.fonts.ready` (the core Arabic-font quality promise is currently a no-op — and was never validated, since the spike has the same bug).
4. **H1** — Enforce concurrency-1 on the `long` queue in code (the OOM-safety guarantee is currently only prose).
5. **B4 + B5** — Fix `modules.txt`/module-folder and git-root/app-root layout (the app won't `migrate` or `get-app` cleanly as shipped).
6. **H4 + H6** — Confine + permission-check `inline_images` and sanitize `doc.terms` (a Quotation editor can exfiltrate arbitrary private files into a downloadable PDF).