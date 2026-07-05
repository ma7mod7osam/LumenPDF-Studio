This is a planning/documentation task. The deployment memory confirms the Cloudways environment realities (SSH/SFTP access, master-user file-creation limits, secrets-injection discipline, Varnish purges, server-side curl testing) that I'll fold into the plan. Note: that memory is about the *WordPress/static assessment site*; this BrandPDF task is a *separate ERPNext/Frappe app*, so I'll keep the Cloudways operational lessons but not the WP-specific bits.

Here is the technical execution plan.

---

# BrandPDF for ERPNext — Technical Execution Plan

*Concrete, build-from-this spec. Phase 1 target: BSTC Quotation, one button, pixel-perfect via real Chromium.*

## 0. Decisions locked before any code

| Decision | Phase 1 | Rationale |
|---|---|---|
| **Engine** | **Playwright on the existing Chromium** (in-process), behind an abstraction | Fastest path to a working loop on a single Cloudways box; Chromium + libs already present (print_designer). Gotenberg becomes a config flip in Phase 2 once Docker is confirmed in M0. |
| **Template source of truth** | **Jinja file in the app** | No DocType round-trip; the owner already has the proven HTML. Move to a DocType in Phase 2. |
| **Invocation** | **Background job for >1 page or attach; sync for instant download** | Keeps the web worker responsive; headless Chromium is heavy. |
| **Assets** | **base64-inline by default** | Proven to render; immune to container/file-URL reachability differences; makes the engine choice irrelevant to asset handling. |

**M0 gate (do this first, on the real server, before writing app code):**
```bash
# confirm the chromium print_designer ships, and that we can drive it ourselves
ssh <bench-host>
bench --site <site> console     # then: import frappe; print(frappe.get_hooks())  # sanity
# find the chromium binary print_designer uses
ls -la ~/.cache/ms-playwright/ 2>/dev/null
which chromium chromium-browser google-chrome 2>/dev/null
find / -name 'chrome' -path '*chromium*' 2>/dev/null | head
# confirm Docker availability for the Phase-2 Gotenberg decision
docker version 2>/dev/null && echo "DOCKER OK" || echo "NO DOCKER -> Playwright stays primary"
```
Exit criteria: render the owner's proven HTML to a correct PDF *from the server* with our own options. If that passes, everything downstream is packaging.

---

## 1. App layout, hooks, endpoint, UI wiring

### 1.1 Folder structure
```
brandpdf/
├── pyproject.toml
├── README.md
├── docker/
│   └── gotenberg.compose.yml          # Phase 2 bring-up
├── brandpdf/
│   ├── hooks.py
│   ├── modules.txt
│   ├── patches.txt
│   ├── api.py                         # whitelisted endpoints
│   ├── render/
│   │   ├── __init__.py
│   │   ├── base.py                    # Renderer ABC: render(html, options) -> bytes
│   │   ├── playwright_engine.py
│   │   ├── gotenberg_engine.py        # Phase 2
│   │   └── factory.py                 # get_renderer() reads site_config brandpdf_engine
│   ├── core/
│   │   ├── context.py                 # build_render_context(doc, branding)
│   │   ├── branding.py                # resolve_branding(company) -> dict
│   │   ├── templating.py              # render_html(doctype,name,template) sandboxed Jinja
│   │   └── assets.py                  # inline_assets(html) -> base64 data URIs
│   ├── templates/
│   │   └── brandpdf/
│   │       └── quotation_bstc.html    # Phase 1 proven HTML, Jinja-ized
│   ├── public/
│   │   └── js/brandpdf_button.js      # form button (doctype_js)
│   ├── config/
│   │   └── brandpdf.py                # desk module config (Phase 2)
│   └── brandpdf/doctype/             # Phase 2 config DocTypes
│       ├── brandpdf_settings/
│       ├── brandpdf_template/
│       └── brandpdf_mapping/
```

### 1.2 `hooks.py` (key entries)
```python
app_name = "brandpdf"

# Phase 1: inject the form button on Quotation (Phase 2: read mapping for all mapped doctypes)
doctype_js = {"Quotation": "public/js/brandpdf_button.js"}

# Phase 2 integrations (added incrementally, never monkey-patch core):
# auto-attach on submit
doc_events = {
    "Quotation":     {"on_submit": "brandpdf.api.auto_attach"},
    "Sales Invoice": {"on_submit": "brandpdf.api.auto_attach"},
}
# Phase 2: route the standard Print/PDF + Email-attach through us for mapped doctypes
# override_doctype_class / pdf_generator hook OR a custom print_format hook — see §1.5

# scheduled cleanup of temp render artifacts (Phase 2)
scheduler_events = {"daily": ["brandpdf.core.assets.cleanup_tmp"]}

fixtures = ["BrandPDF Settings", "BrandPDF Template", "BrandPDF Mapping"]  # Phase 2
```

### 1.3 Whitelisted endpoint signatures (`api.py`)
```python
import frappe

@frappe.whitelist()                          # requires a logged-in session (not guest)
def download(doctype: str, name: str, template: str | None = None):
    """Stream a branded PDF as a download. Sync path."""
    _authorize(doctype, name)                # read perm + allowlist check (see §4)
    html  = render_html(doctype, name, template)        # sandboxed Jinja
    pdf   = get_renderer().render(html, _pdf_options(doctype, name))
    frappe.local.response.filename = f"{_safe_name(doctype, name)}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "download"

@frappe.whitelist()
def enqueue_download(doctype: str, name: str, template: str | None = None):
    """For multi-page / heavy docs: render in a background job, return job id;
       client polls and downloads the resulting File. Returns {job_id}."""
    _authorize(doctype, name)
    job = frappe.enqueue("brandpdf.api._render_to_file",
                         queue="long", timeout=120,
                         doctype=doctype, name=name, template=template,
                         user=frappe.session.user)
    return {"job_id": job.id}

@frappe.whitelist()
def auto_attach(doc, method=None):
    """doc_events hook: render + attach branded PDF as a File on submit (Phase 2)."""
    if not _mapping_enabled(doc.doctype):
        return
    pdf  = get_renderer().render(render_html(doc.doctype, doc.name), _pdf_options(doc.doctype, doc.name))
    _save_file(doc, pdf)                      # private File, attached_to_doctype/name
```

**Why `@frappe.whitelist()` and not `allow_guest=True`:** the endpoint must run as the logged-in user so `has_permission` reflects their role. Never expose guest access.

### 1.4 Form button (`public/js/brandpdf_button.js`)
```javascript
frappe.ui.form.on("Quotation", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__("Download Branded PDF"), () => {
      // open via a GET to the whitelisted method so the browser handles the download
      const url = frappe.urllib.get_full_url(
        "/api/method/brandpdf.api.download"
        + `?doctype=${encodeURIComponent(frm.doc.doctype)}`
        + `&name=${encodeURIComponent(frm.doc.name)}`
      );
      window.open(url, "_blank");
    }).addClass("btn-primary");
  },
});
```
Phase 2: replace the hard-coded `"Quotation"` with a generic loader that reads enabled mappings and registers the button on every mapped DocType.

### 1.5 Print / Email / Attach integration (Phase 2 specifics)
- **Print/PDF button**: Frappe v15 supports a `pdf_generator` concept (this is exactly what print_designer hooks). Register a `brandpdf` generator so the stock **Print > PDF** routes through `get_renderer()` for mapped DocTypes; fall back to stock for unmapped. This avoids overriding the UI — it reuses the existing print toolbar.
- **Email attach**: override the attachment builder via `make_communication`/the email dialog's `get_pdf` path for mapped doctypes only (least surprise). Concretely, hook the point where the Email dialog builds `print_format` attachments and substitute our bytes when a mapping exists; leave everything else stock.
- **Attach-on-submit**: the `doc_events on_submit` above, gated by a per-mapping `auto_attach` checkbox.

---

## 2. Config model (no-code for the business)

Three DocTypes (Phase 2). Phase 1 hard-codes equivalents in `branding.py`/the template.

### 2.1 `BrandPDF Settings` (per company)
Single-per-company (Link to Company, unique). Fields:

| Fieldname | Type | Notes |
|---|---|---|
| `company` | Link → Company | unique key; branding resolves by `doc.company` |
| `header_image` | Attach Image | full-bleed header banner (e.g. `/files/bstc_header.png`) |
| `footer_image` | Attach Image | full-bleed footer banner |
| `logo` | Attach Image | optional inline logo |
| `primary_color` | Data (hex) | `#1C75BC` — validated `^#[0-9A-Fa-f]{6}$` |
| `secondary_color` | Data (hex) | `#1A1E2A` (navy) |
| `accent_color` | Data (hex) | optional (zebra/total-bar) |
| `font_family` | Data / Select | bundled fonts only (see §3.5); no arbitrary CDN |
| `page_size` | Select | A4 / Letter (default A4) |
| `margin_top/right/bottom/left` | Float (mm) | default 0; the whole point is *we* set these |
| `rtl` | Check | enables `dir="rtl"`, Arabic font, RTL table flow |
| `footer_registration_text` | Small Text | CR no., VAT no., etc. |
| `default_engine` | Select | playwright / gotenberg (overrides site default) |

### 2.2 `BrandPDF Template`
| Fieldname | Type | Notes |
|---|---|---|
| `template_name` | Data | e.g. "Quotation – Standard", "Quotation – Tender" |
| `target_doctype` | Link → DocType | |
| `language` | Select | en / ar / bilingual |
| `body` | Code (Jinja/HTML) | the template source (Phase 2 in-DB editing) |
| `is_standard` | Check | shipped starter (read-only; clone to edit) |

How a template is **authored/stored/edited**:
- **Phase 1**: a `.html` file in `templates/brandpdf/`. Edited in the repo, deployed via SFTP.
- **Phase 2**: stored in `BrandPDF Template.body`, edited in the desk Code editor. Standard templates ship as **fixtures** (read-only); the business **Duplicates** one to customize, so `bench migrate` never clobbers their edits.
- **Long-term option**: map to a print_designer Print Format and render *its* HTML through our engine (reuse their visual editor, our correct output). Keep this behind a `source_type` select (`jinja_file` / `template_doctype` / `print_format`).

### 2.3 `BrandPDF Mapping`
| Fieldname | Type | Notes |
|---|---|---|
| `target_doctype` | Link → DocType | |
| `condition` | Small Text (optional) | safe expression, e.g. `doc.transaction_type=="Tender"` → picks a template |
| `template` | Link → BrandPDF Template | |
| `enabled` | Check | |
| `auto_attach` | Check | render+attach on submit |
| `replace_print_pdf` | Check | route stock Print>PDF through us |
| `replace_email_attach` | Check | substitute the email attachment |

**Resolution at render time:** `doctype → enabled mappings → first whose condition passes → template`; branding from `doc.company → BrandPDF Settings`. This is the "no code each time" spine: onboarding is filling forms.

---

## 3. Engine integration (Playwright primary; Gotenberg Phase 2)

### 3.1 Install on Cloudways (Playwright path)
```bash
# in the bench's python env
ssh <bench-host>
cd ~/frappe-bench
./env/bin/pip install playwright

# DO NOT 'playwright install' a fresh browser (apt/root may be blocked, and Chromium already exists).
# Instead point Playwright at the print_designer Chromium found in M0:
bench set-config -g brandpdf_engine playwright
bench set-config -g brandpdf_chromium_path "/abs/path/to/chromium"   # from M0 discovery
# If Playwright insists on its own chromium and root apt is available:
#   ./env/bin/playwright install-deps chromium && ./env/bin/playwright install chromium
# but prefer reusing the existing binary to avoid the chromium_path gotcha.
```
Note the verified config gotcha: print_designer uses `chromium_binary_path` vs others' `chromium_path`. We namespace ours as **`brandpdf_chromium_path`** and never read theirs, so a print_designer change can't break us.

### 3.2 Renderer interface (`render/base.py`)
```python
class Renderer:
    def render(self, html: str, options: dict) -> bytes:
        raise NotImplementedError
```

### 3.3 Playwright engine (`render/playwright_engine.py`)
```python
from playwright.sync_api import sync_playwright
import frappe

class PlaywrightRenderer(Renderer):
    def render(self, html: str, options: dict) -> bytes:
        chromium_path = frappe.conf.get("brandpdf_chromium_path")  # explicit, namespaced
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium_path or None,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                page = browser.new_page()
                # assets already base64-inlined -> no network needed
                page.set_content(html, wait_until="networkidle", timeout=options["nav_timeout_ms"])
                page.emulate_media(media="print")
                pdf = page.pdf(
                    prefer_css_page_size=True,    # respect @page{size:A4}
                    print_background=True,        # banners, blue header, zebra, total bar
                    margin={"top":"0","right":"0","bottom":"0","left":"0"},  # full-bleed; CSS owns margins
                    display_header_footer=False,  # footer is the <tfoot> in the wrapping table
                    # (Optional Chromium native header/footer template path if a doc needs it)
                )
                return pdf
            finally:
                browser.close()
```
These are exactly the options Frappe's wrapper hid — `prefer_css_page_size`, `print_background`, `margin:0`. This is the move that makes 25 rounds of failure succeed.

### 3.4 Gotenberg engine (`render/gotenberg_engine.py`, Phase 2)
```bash
# docker/gotenberg.compose.yml — single container on the same server
# image: gotenberg/gotenberg:8 ; expose 127.0.0.1:3000 only (never public)
docker compose -f docker/gotenberg.compose.yml up -d
bench set-config -g brandpdf_engine gotenberg
bench set-config -g brandpdf_render_url "http://127.0.0.1:3000"
```
```python
class GotenbergRenderer(Renderer):
    def render(self, html, options):
        url = frappe.conf["brandpdf_render_url"] + "/forms/chromium/convert/html"
        files = {"index.html": ("index.html", html)}              # assets inlined as base64
        data  = {"marginTop":"0","marginBottom":"0","marginLeft":"0","marginRight":"0",
                 "printBackground":"true","preferCssPageSize":"true",
                 "paperWidth":"8.27","paperHeight":"11.69"}        # A4 inches if not CSS-driven
        r = requests.post(url, files=files, data=data, timeout=options["http_timeout_s"])
        r.raise_for_status()
        return r.content
```
Bind Gotenberg to `127.0.0.1` only (it can fetch remote URLs — keep it off the public net to avoid being an SSRF proxy). With assets inlined, it never needs network at all.

### 3.5 Image / font / asset handling (`core/assets.py`)
- **Default = base64 inline.** Walk the rendered HTML, replace `<img src="/files/...">` and CSS `url(/files/...)`/`@font-face src` with `data:<mime>;base64,...`. Read files from the bench's `sites/<site>/public/files` (private files via `frappe.get_doc("File")` + permission check). This removes all cross-engine URL-reachability risk (the §6 "asset reachability" risk) and matches the owner's already-proven artifact.
- **Fonts**: bundle the brand + Arabic fonts (e.g. an Arabic webfont) inside the app at `public/fonts/`, inline them as `@font-face` base64. **No CDN `@import`** (the verified wkhtmltopdf flaky-font cause; also an SSRF/availability risk). RTL: set `dir="rtl"` and the Arabic font when `branding.rtl`.
- Cap total inlined size (e.g. warn >8 MB) to avoid huge HTML payloads.

### 3.6 PDF options builder (`_pdf_options`)
```python
def _pdf_options(doctype, name):
    s = resolve_branding(get_company(doctype, name))
    return {
        "nav_timeout_ms": 30000,
        "http_timeout_s": 30,           # gotenberg
        "page_size": s.get("page_size", "A4"),
        # margins live in CSS @page; we pass 0 to the engine so CSS wins
    }
```

### 3.7 Concurrency / performance
- **Sync** path (`download`): launch → render → close per request, with a **per-worker concurrency guard** (a Redis lock or a small semaphore: max 2 concurrent Chromium launches per node) so a burst can't OOM the box. `--disable-dev-shm-usage` is mandatory on Cloudways (small `/dev/shm`).
- **Heavy/attach** path: `frappe.enqueue(queue="long", timeout=120)` background job → write a private File → notify client (realtime `publish_realtime` or poll). Auto-attach-on-submit always goes through the queue so submit latency is unaffected.
- **Browser reuse**: Phase 1 launches per request (simplest, safe). Phase 2 optimization: a long-lived browser with new `context`/`page` per render, or switch to **Gotenberg** which pools natively (the cleaner answer than managing a Chromium pool in Python).
- **Timeouts**: 30 s nav + a hard job timeout; on timeout, kill the browser, log, return a clean error to the button.

---

## 4. Security & permissions

| Threat | Control |
|---|---|
| **AuthZ / IDOR** | `_authorize`: require login (no guest); `doc = frappe.get_doc(doctype, name)`; `doc.has_permission("read")` or `frappe.has_permission(doctype, "read", doc)` → else `frappe.throw(PermissionError)`. The user only renders docs they can read. |
| **DocType allowlist** | Only render DocTypes that have an **enabled mapping** (Phase 2) or the hard-coded `Quotation` (Phase 1). Reject arbitrary `doctype` values → prevents using the endpoint to dump unrelated doctypes' fields. |
| **Template injection (SSTI)** | Render templates with Frappe's **sandboxed Jinja** (`frappe.render_template` / `is_safe_exec`-style sandbox), NEVER raw `jinja2.Template(...).render()`. Standard templates are read-only fixtures. Business-edited templates run sandboxed; document the residual risk (template editing is a privileged System-Manager action anyway). |
| **`condition` expressions** | Evaluate mapping conditions with Frappe's **safe_eval** (restricted globals), not `eval()`. |
| **SSRF** | Assets are inlined from the local filesystem — the renderer makes **no outbound requests**. Playwright: no remote nav. Gotenberg: bound to `127.0.0.1`, and since HTML is fully inlined it never fetches. Block `file://` traversal: resolve `/files/...` only within the site's files dir; reject `..`, absolute paths, and non-`/files` URLs. |
| **Renderer sandbox** | Chromium launched headless with `--no-sandbox` only because the container/Cloudways user is already unprivileged; run under the bench user, never root. Gotenberg adds OS-level isolation (container) — a Phase-2 security win. |
| **Resource exhaustion / DoS** | Concurrency semaphore (§3.7), payload size cap (§3.5), hard timeouts, rate-limit the endpoint per user (`frappe.rate_limiter`). |
| **Secrets** | No new secrets in Phase 1. Any future license/SaaS key follows the project's verified discipline: inject server-side only, never commit, key-preserve on deploy (mirrors the store.php/ai-proxy.php rule in project memory). |
| **Filename injection** | `_safe_name` strips path separators/control chars from the download filename. |

---

## 5. Deployment, packaging, upgrade strategy

### 5.1 Install (single-site owner)
```bash
ssh <bench-host>; cd ~/frappe-bench
bench get-app https://github.com/<owner>/brandpdf    # or local path during dev
bench --site <site> install-app brandpdf
./env/bin/pip install playwright
bench set-config -g brandpdf_engine playwright
bench set-config -g brandpdf_chromium_path "<path from M0>"
bench --site <site> migrate
bench build --app brandpdf
bench restart
```

### 5.2 Cloudways operational realities (carried from project memory, applied to bench)
- **SSH/bench available; root/apt may be restricted** → reuse the existing Chromium; don't rely on `playwright install-deps`. (M0 confirms.)
- **No Varnish concern for the API** (`/api/method/...` is dynamic, not full-page cached). But **`bench build` asset cache-busting** handles the JS button — bump on deploy; Frappe fingerprints assets so a hard refresh is the only client step.
- **File-creation permission quirks** seen on the WP side don't apply to the bench (owner owns the bench dir), but still deploy via `bench get-app`/git pull, not ad-hoc scp of single files.
- **Test the endpoint server-side first** (mirrors the project's curl-on-loopback habit), bypassing any edge protection:
  ```bash
  bench --site <site> execute brandpdf.api.download --kwargs "{'doctype':'Quotation','name':'<QTN>'}"
  # or hit it authenticated:
  curl -s -b "sid=<session>" "https://127.0.0.1/api/method/brandpdf.api.download?doctype=Quotation&name=<QTN>" -H "Host: <site>" -o /tmp/out.pdf
  ```

### 5.3 Upgrade-safety rules (productization-critical)
- **No monkey-patching** of Frappe/ERPNext core — only `hooks.py` (doctype_js, doc_events, pdf_generator hook, scheduler_events).
- **All config namespaced** `brandpdf_*` in site_config + our own DocTypes; never read print_designer's keys.
- **Engine isolated** behind the abstraction — a Chromium/Playwright/Gotenberg bump never touches business code.
- **Standard templates as read-only fixtures**; business edits live in Duplicated records so `migrate` can't clobber them.
- **Version pinning**: pin Playwright + Gotenberg image tag; run the visual-regression suite (§6) against each ERPNext v15 point release before declaring compatibility.

### 5.4 Packaging for sale (Phase 2+)
- Repo ships: the app, `docker/gotenberg.compose.yml`, starter templates (fixtures), an onboarding wizard, docs.
- Two install paths documented: **Playwright (no container)** and **Gotenberg (container)** — selected by `brandpdf_engine`.
- List on Frappe Cloud Marketplace once Phase 2 is stable.

---

## 6. Build order — ordered checklist with acceptance criteria

### MVP (Phase 1 — BSTC Quotation)

- [ ] **T0 — M0 spike (server)**
  *Do:* run the M0 commands; locate Chromium; confirm/deny Docker; render the owner's proven HTML to PDF from the server with our options.
  *Accept:* a PDF on the server that visually matches the owner's reference (full-bleed header/footer repeating, blue header, zebra, total bar, correct margins, clean Arabic). Engine choice recorded in `brandpdf_engine`.

- [ ] **T1 — App scaffold + renderer abstraction**
  *Do:* `bench new-app brandpdf`; add `render/base.py`, `playwright_engine.py`, `factory.py` (reads `brandpdf_engine`).
  *Accept:* `get_renderer().render(known_html, opts)` returns valid PDF bytes from a bench console call.

- [ ] **T2 — Quotation Jinja template**
  *Do:* port the proven `<table>/<thead>/<tfoot>` full-bleed HTML into `templates/brandpdf/quotation_bstc.html`; parametrize colors/banners/currency(BHD)/EN-AR via a context dict (still hard-coded values acceptable).
  *Accept:* `render_html("Quotation", <name>)` produces HTML that renders identically to T0's static file when fed real Quotation data.

- [ ] **T3 — Asset inlining**
  *Do:* implement `inline_assets` (images + bundled fonts → base64); bundle Arabic + brand fonts in `public/fonts/`.
  *Accept:* rendered PDF has zero outbound requests (verify via Playwright network log empty); fonts/banners render with the network disabled.

- [ ] **T4 — Whitelisted `download` endpoint + authorization**
  *Do:* implement `download` + `_authorize` (login + `has_permission(read)` + Quotation allowlist) + `_safe_name`.
  *Accept:* a permitted user downloads the PDF; a user without read perm on that Quotation gets `PermissionError` (403), not a PDF; an unknown doctype is rejected.

- [ ] **T5 — Form button**
  *Do:* `doctype_js` → `brandpdf_button.js` adds the primary "Download Branded PDF" button on saved Quotations.
  *Accept:* button appears on a saved Quotation, click downloads the correct branded PDF; hidden on new/unsaved.

- [ ] **T6 — Concurrency guard + timeouts + error UX**
  *Do:* per-node semaphore (max 2), 30 s nav timeout, `--disable-dev-shm-usage`; clean error surfaced to the button on failure/timeout.
  *Accept:* 5 simultaneous clicks don't OOM the box; a forced render error shows a readable message, not a stack trace.

### Hardening (Phase 1.5)

- [ ] **T7 — Real-data Arabic/RTL pass**
  *Accept:* renders correctly with mixed LTR numbers in RTL lines, long bilingual product names, multi-page line items (header repeats every page, footer pinned, no clipping).

- [ ] **T8 — Attach-to-doc + background path**
  *Do:* `enqueue_download` + `_render_to_file` (private File attached to the Quotation); optional `auto_attach` on submit behind a flag.
  *Accept:* heavy/multi-page render runs in a `long` job without blocking; resulting File is private and permission-scoped.

- [ ] **T9 — Golden-PDF regression test**
  *Do:* a test that renders the showcase Quotation and diffs against a committed golden PDF (image-diff of rasterized pages).
  *Accept:* CI/`bench run-tests` fails on any visual drift beyond a small threshold.

### Product (Phase 2 — config spine, multi-DocType, integrations)

- [ ] **T10 — Config DocTypes** (`BrandPDF Settings`, `Template`, `Mapping`) with hex/expression validation; branding resolves by `doc.company`.
  *Accept:* re-skin BSTC (colors/banners/footer text) entirely via the Settings form, no code change; standard templates ship as read-only fixtures, Duplicate-to-edit survives `migrate`.

- [ ] **T11 — Mapping-driven button + template resolution** (generic loader replaces hard-coded Quotation; `condition` via safe_eval).
  *Accept:* a second template ("Quotation – Tender") is selected by a condition; the button registers automatically on every enabled mapped DocType.

- [ ] **T12 — Sales Invoice template + ≥1 more.**
  *Accept:* Sales Invoice renders branded with its own totals/tax layout; both render correctly bilingual.

- [ ] **T13 — Print/Email/Attach integration** (`pdf_generator` hook for Print>PDF; email-attach substitution; auto-attach-on-submit) — all gated per mapping (`replace_print_pdf`, `replace_email_attach`, `auto_attach`).
  *Accept:* stock Print>PDF and the Email dialog produce our branded PDF for mapped doctypes only; unmapped doctypes behave exactly as stock (least surprise).

- [ ] **T14 — Gotenberg engine + Docker bring-up** (only if M0 confirmed Docker) behind `brandpdf_engine=gotenberg`, bound to `127.0.0.1`.
  *Accept:* identical PDF output via Gotenberg; flipping `brandpdf_engine` requires no code change; renderer reachable only on loopback.

- [ ] **T15 — Onboarding wizard + starter library + docs + upgrade pass.**
  *Accept:* a fresh business configures branding + picks a starter template + previews + downloads, entirely via forms; visual-regression suite green against the current ERPNext v15 point release.

---

### Single-developer realism notes
- **Critical path is T0 only.** If T0's PDF matches the reference, the rest is plumbing the owner has effectively de-risked. Do not start the config spine (T10) until T1–T9 prove the loop on real BSTC quotations — the reference PDF is the spec; match it first, generalize second.
- **Stay on Playwright for Phase 1** even if you intend Gotenberg later; the abstraction (T1) keeps that reversible at zero rewrite cost.
- **Reuse the project's proven Cloudways discipline**: test server-side on loopback first, namespace all config, never commit secrets, key-preserve on deploy.

Relevant paths (to create): app root `~/frappe-bench/apps/brandpdf/`; Phase-1 template `brandpdf/brandpdf/templates/brandpdf/quotation_bstc.html`; engine `brandpdf/brandpdf/render/`; endpoint `brandpdf/brandpdf/api.py`; button `brandpdf/brandpdf/public/js/brandpdf_button.js`.