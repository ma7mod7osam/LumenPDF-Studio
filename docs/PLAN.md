This is a planning/documentation task. I have all four upstream inputs (Planner, Executer, QA Review) plus the project context. My job is to synthesize the final approved build document. Let me produce it directly.

# BrandPDF for ERPNext — Final Approved Plan

*A custom Frappe app that renders pixel-perfect, branded PDFs through a real Chromium engine — bypassing Frappe's PDF wrapper. Phase 1 customer-zero: BSTC (Building Solutions Trading & Contracting W.L.L), Bahrain.*

---

## 1. Executive summary

We are building **BrandPDF**, a custom Frappe/ERPNext v15 app that generates branded, multi-page PDFs (Quotations first, then Sales Invoices and beyond) by taking control of the Chromium `printToPDF` call ourselves and setting the options Frappe's generator layer hides (`preferCSSPageSize`, `printBackground`, `margin:0`, font-ready gating). The owner has already empirically proven the only fact that matters — the target HTML renders perfectly in real Chromium — so this is fundamentally an *un-wrapping* project, not a rendering-research project: low technical risk on the core, high polish effort on the edges. It wins because it solves the exact four-things-at-once that both stock engines (wkhtmltopdf and print_designer's chrome generator) cannot do simultaneously: **full-bleed repeating banners + exact margins + reliable backgrounds + clean RTL/Arabic**. Phase 1 makes BSTC's branded Quotation real with one button; Phases 2–3 turn that proven loop into a configurable, sellable product for the sharpest-pain segment (ERPNext SMBs and implementation partners in MENA/RTL markets). The whole project hinges on one M0 spike that must validate the footer-on-a-short-page behavior before any app code is written.

---

## 2. Final architecture & engine decision

### 2.1 Engine: **Playwright driving Chromium (committed for Phase 1), behind a one-method engine abstraction. Gotenberg is the named Phase-2 fallback/option — never the Phase-1 primary.**

This overrides the Planner's "Gotenberg-first" instinct and adopts the Executer's correction, hardened by the QA review.

**Why Playwright now (not Gotenberg):**
- The decisive constraint is **managed Cloudways**: apt/root restricted, Imunify360 blocks automation, and a persistent Docker daemon/long-running container is *not* reliably available on the managed tier (the Cloudways "Docker works" material refers to root/VPS/Autonomous tiers, not managed — QA Blocker #3). Making a containerized service the Phase-1 dependency is a mirage.
- Chromium + its system libraries are **already on the box** because print_designer's chrome generator runs. We render in-process, no new infra.
- The engine sits behind a `render(html, options) -> bytes` interface (`GotenbergRenderer` / `PlaywrightRenderer` selected by a namespaced `brandpdf_engine` config key), so the Gotenberg decision stays **reversible at zero rewrite cost** — and the SaaS-rendering story (a hosted Gotenberg endpoint) remains open for Phase 3 if a separate VPS is ever justified.

**Why not WeasyPrint:** it is not Chromium. The owner's entire proof rests on "this exact HTML renders perfectly *in Chromium*." Switching engines throws away the verified artifact and reopens the CSS-compat fight. Rejected from the stack entirely.

### 2.2 How it fixes each verified problem

| Verified stock-engine failure | How BrandPDF fixes it |
|---|---|
| wkhtmltopdf: no `var()`, broken flexbox, unreliable backgrounds | Real Chromium understands modern CSS natively; `printBackground:true` forces backgrounds. |
| wkhtmltopdf/print_designer: flaky CDN web fonts, blurry Arabic | Fonts **bundled in the app** and loaded locally + an explicit `document.fonts.ready` gate before `page.pdf()` (no CDN, no race — QA High #5). |
| chrome generator: ignores margin fields → fixed ~16mm border | **We** set `margin:0` on the `printToPDF` call; CSS `@page{margin:0}` + `preferCSSPageSize:true` own the layout. Full-bleed achieved. |
| chrome generator: no reliable page-pinned `<tfoot>` footer | Resolved by the committed footer model below (QA Blockers #1/#2) — validated on a short page in M0 before building. |
| chrome generator: classic image Letter Heads ignored for custom HTML | We render our own Jinja HTML and never invoke the Frappe/print_designer generator, so Letter Head injection is irrelevant. |
| Frappe wrapper hides `printToPDF` options | We call Chromium directly and own every option. This is the core move. |

### 2.3 Data flow (happy path)
```
Quotation form → "Download Branded PDF" button
   → frappe.call (POST) brandpdf.api.request_pdf {doctype, name, template}
      (server, @frappe.whitelist, logged-in user)
      1. _authorize: login + doc.has_permission("read") + DocType allowlist
      2. resolve branding (doc.company → settings, with safe default fallback)
      3. resolve template (Phase 1: Jinja file; Phase 2: mapping → template)
      4. render Jinja (sandboxed) → HTML
      5. inline assets (images base64; fonts local/served)
      6. ENQUEUE render job (long queue, single browser-owning worker)
   → client polls get_job_result(job_id) → private File URL (TTL) → download
```
All rendering happens **outside** the Frappe PDF pipeline. We never call `frappe.utils.pdf.get_pdf` or print_designer's generator.

---

## 3. QA findings — resolutions adopted

Every BLOCKER and HIGH below has a committed resolution. No hand-waving.

### Blockers

**B1 — `<tfoot>` footer does NOT pin to the bottom on a short/last page.** *Adopted: zero-margin model with a CSS `position: fixed; bottom: 0` footer band, NOT native header/footer templates.* The repeating top banner stays as `<thead>` in the wrapping table (it genuinely repeats correctly). The footer becomes a **fixed-position band** so it pins to the bottom of *every* page including short/last pages, while the `<thead>` reserves top space. M0 **must** render a quotation whose last page is half-empty and confirm footer position before any app code. This is the single load-bearing validation. *(If the fixed-band approach shows content-overlap issues in M0, the documented fallback is to accept footer-floats-on-last-page for Phase 1 and revisit — but the fixed band is the committed first choice.)*

**B2 — full-bleed `@page{margin:0}` and native Chromium header/footer templates are mutually exclusive.** *Adopted: commit to the zero-margin `<thead>`/fixed-footer-band model; drop all references to native `headerTemplate`/`footerTemplate` for the banners.* `display_header_footer=False` always. Native templates are reserved *only* for an optional page-number line in a future phase, and only with the explicit understanding that enabling them reintroduces the margin conflict (so page numbers, if needed, are drawn in-CSS within the fixed footer band instead).

**B3 — Docker on managed Cloudways is unreliable; Gotenberg-primary rests on it.** *Adopted: Playwright is the committed Phase-1 engine.* Gotenberg is demoted to "Phase 2/3, only after M0 proves a persistent container survives on the actual plan (reboot test + 24h soak)." The SaaS-rendering story, if pursued, requires a *separate* VPS — it is not "free."

### Highs

**H4 — Playwright may refuse print_designer's Chromium (revision/CDP mismatch).** *Adopted as an explicit M0 sub-gate.* Do not assume `executable_path=<existing chromium>` works. M0 exit criteria: "Playwright renders via the existing binary **OR** via a user-cache `playwright install chromium` (browser only, no root — system libs already present) **OR** via direct CDP." Whichever passes becomes the committed Phase-1 path. The "DO NOT playwright install" advice is downgraded from a rule to a preference.

**H5 — `networkidle` + base64 assets is wrong; fonts may render as fallback.** *Adopted.* Use `set_content(html, wait_until="load")` then `page.evaluate("document.fonts.ready")` before `page.pdf()`. This is the correct font-readiness gate and removes the top source of intermittent font corruption.

**H6 — endpoint IDOR-adjacent gap + CSRF/GET exposure.** *Adopted.* (a) The button calls the endpoint via **POST through `frappe.call`** returning a temp-file URL, not `window.open(GET)`. (b) Authorization enforces `doc.has_permission("read")` AND respects **field-level permlevel** — template authors are documented as forbidden to embed permlevel-restricted fields, and a test asserts a read-but-not-permlevel-1 user never sees restricted fields in the PDF.

**H7 — per-process semaphore is unenforceable across workers; sync-by-default OOMs a managed box.** *Adopted (this is the architecture, not a tweak).* All renders are **enqueued to the `long` queue**, served by **a single dedicated worker that owns one long-lived browser** (new context per render). Memory is bounded to one Chromium; renders serialize. The button shows a spinner and polls. A Redis counter guards against accidental fan-out. This single change also resolves H14 (zombies).

**H8 — sandboxed Jinja / `safe_eval` oversold as a security boundary.** *Adopted, stated honestly.* The Jinja sandbox is **defense-in-depth, not a guarantee**. `BrandPDF Template` write permission is **hard-locked to System Manager** with a permission test. Mapping `condition` logic is implemented as **structured filter rows (fieldname/operator/value)**, eliminating free-form `eval`/`safe_eval` entirely. We track Frappe `safe_eval` CVEs against pinned versions.

**H9 — fixtures revert user edits on migrate; `pdf_generator` hook is print_designer-coupled.** *Adopted.* (a) Standard templates are shipped as fixtures **and marked read-only at the DocType level** (edit denied even to System Manager via an `is_standard` guard) so "duplicate to edit" is *enforced*, not suggested — migrate can never clobber a user's work because users physically cannot edit standards. (b) Before committing the Print>PDF integration (Phase 2/T13) we **verify `pdf_generator` is real core v15 API** on the target build; if it is print_designer-only, we integrate via supported `override_whitelisted_methods` / a custom button and document the version dependency.

**H10 — multi-MB inlined HTML (Arabic font + banners) can choke renders.** *Adopted.* Inline **images** (small, portability-critical) as base64; load **fonts locally via served/`file://` URL** for the Playwright path (no network risk) and ship a **pre-subsetted woff2 Arabic font**. Reserve base64-everything for the Gotenberg/portable path only. Measure actual payload in M0.

**H11 — BHD 3-decimal currency + RTL bidi under-tested.** *Adopted.* Use ERPNext's `frappe.utils.fmt_money(value, currency="BHD")` (correct 3 decimals) in the template context; wrap all numbers/dates inside RTL lines in `<bdi>`/`&#8207;` bidi isolation; explicitly choose Western digits (default) and test totals, dates, quantities — not just labels.

### Medium/Low (accepted into the build, condensed)
- **M12 page-breaks:** `tr{break-inside:avoid}` + `break-inside:avoid` on the grand-total bar; test a 50-line quotation; added to acceptance.
- **M13 wedge/economics:** sharpen positioning to "the four-things-at-once stock can't do"; validate willingness-to-pay with 2–3 partners before building the config spine; SaaS-rendering dropped from the near roadmap (Bahrain/Saudi PDPL data-residency risk to the exact beachhead buyer).
- **M15 branding resolution:** safe **default-branding fallback** when no per-company settings exist (never throw); validate banner Files exist/readable at render with a clean error; banners stored **public** (simpler inlining, not sensitive).
- **L16 Letter Head suppression / L17 async contract / L18 M0 script hygiene:** when ever rendering a Print Format, fetch raw body with `with_letterhead=0`; define `get_job_result(job_id)` returning a private, user-scoped File URL with TTL cleaned by the daily scheduler (404 for other users); scope M0 discovery to `find ~/.cache ~/frappe-bench /usr/lib/chromium* /opt -name 'chrome*'` and drop the noisy `get_hooks` line.

---

## 4. Configuration & productization model (concrete)

What the business edits, and where. Phase 1 hard-codes the equivalents; Phase 2 introduces the three-DocType spine so onboarding is **filling forms, not writing Python**.

**`BrandPDF Settings`** (one per Company; branding resolves by `doc.company`):
header/footer/logo images (Attach Image), `primary_color` #1C75BC, `secondary_color` navy #1A1E2A, accent, `font_family` (bundled fonts only), page size (A4 default), margins (default 0), `rtl` toggle, `footer_registration_text` (CR/VAT), `default_engine`. Hex fields regex-validated. Missing record → safe default branding.

**`BrandPDF Template`** (the library): `template_name`, `target_doctype`, `language` (en/ar/bilingual), `body` (Jinja/HTML, Phase 2 in-DB editing), `is_standard` (shipped starters are **read-only — clone to edit**), `source_type` (`jinja_file` / `template_doctype` / `print_format`). Write perm locked to System Manager.

**`BrandPDF Mapping`** (the no-code spine): `target_doctype` → `template`, plus **structured condition rows** (fieldname/operator/value, no eval) to pick between e.g. "Quotation – Tender" vs "Quotation – Standard", and per-mapping toggles `enabled`, `auto_attach`, `replace_print_pdf`, `replace_email_attach`.

**Resolution at render time:** `doctype → enabled mappings → first matching condition → template`; branding from `doc.company`. **Onboarding wizard** (Phase 3): upload banners → pick colors/fonts → choose a starter per DocType → Preview → done. BSTC's setup becomes the first showcase template.

**Packaging:** standard Frappe app (`bench get-app brandpdf && bench --site x install-app brandpdf`), two documented install paths (**Playwright/no-container** default; **Gotenberg/container** optional), Frappe Cloud Marketplace listing once Phase 3 is stable.

**Licensing posture (recommended):** open-core engine + abstraction (adoption + partner goodwill) + a paid **Pro** tier (config spine, template library, integrations) via per-site marketplace license. Partners get a white-label/agency tier — they are the distribution channel. **SaaS rendering deferred** until a self-host-refusing customer actually asks (data-residency liability in MENA).

---

## 5. Phased roadmap

Effort is **relative** (1 ≈ a focused day-unit), not calendar time.

### Phase 1 — MVP: BSTC Quotation live (effort ≈ 13)
Bar: BSTC presses one button on a Quotation and gets the exact PDF the owner proved renders perfectly.

| Milestone | Deliverable / acceptance | Effort |
|---|---|---|
| **M0 — Spike & gates** | On the real server: (a) render the proven HTML to PDF with **our** options; (b) **footer correct on a half-empty last page** (B1); (c) Playwright drives an available Chromium without root (H4); (d) `document.fonts.ready` gate works, Arabic renders (H5); (e) measure inlined payload (H10); (f) record Docker availability for later. **Exit: a server-side PDF visually matching the reference, with a correct short-page footer.** | 3 |
| **M1 — App + renderer + template** | `brandpdf` app; `render/` abstraction + `PlaywrightRenderer`; one Quotation Jinja template (zero-margin `<thead>` + fixed footer band); BHD/`fmt_money` + `<bdi>` bidi in context. **Accept:** `get_renderer().render(...)` returns valid PDF from console; HTML matches M0 when fed real Quotation data. | 5 |
| **M2 — Endpoint, button, queue** | POST `request_pdf` + `_authorize` (login + read perm + permlevel + Quotation allowlist); single-browser `long`-queue worker (H7); `get_job_result` + private TTL File (L17); form button via `frappe.call` (H6); asset inlining (images base64, font local). **Accept:** permitted user downloads correct PDF; no-perm user gets 403; restricted permlevel fields absent; 5 simultaneous clicks don't OOM. | 5 |

### Phase 2 — Hardening + config spine (effort ≈ 12)

| Milestone | Deliverable / acceptance | Effort |
|---|---|---|
| **M3 — Production hardening** | Real-data Arabic/RTL pass (mixed LTR numbers, long bilingual names); 50-line multi-page (header repeats, footer pinned, `break-inside:avoid` rows + total bar, no orphan/clip — M12); error UX (no stack traces); zombie-reaper watchdog + daily temp cleanup (H14); **golden-PDF regression test** (rasterized diff). **Accept:** BSTC uses it for real quotations; CI fails on visual drift. | 5 |
| **M4 — Config spine (no-code)** | `BrandPDF Settings`/`Template`/`Mapping` DocTypes; branding by `doc.company` + default fallback (M15); standards read-only fixtures (H9); structured-condition mapping (H8). **Accept:** re-skin BSTC entirely via forms, no code change; `migrate` cannot clobber user edits. | 4 |
| **M5 — Multi-DocType + integrations** | Sales Invoice template + ≥1 more; auto-attach-on-submit (gated); Print>PDF + email-attach **only after verifying `pdf_generator` is core v15** else fall back to supported hooks (H9b), gated per mapping. **Accept:** mapped doctypes route through us; unmapped behave exactly as stock (least surprise). | 3 |

### Phase 3 — Productization for other ERPNext businesses (effort ≈ 10)

| Milestone | Deliverable / acceptance | Effort |
|---|---|---|
| **M6 — Package & validate** | Onboarding wizard, starter template library, docs site, both install paths, upgrade-safety pass, visual-regression suite green on current v15 point release; **willingness-to-pay validated with 2–3 partners** before heavy investment (M13). **Accept:** a fresh business configures + previews + downloads entirely via forms. | 5 |
| **M7 — Go-to-market** | Marketplace listing; open-core + paid Pro license; partner/white-label tier. **Gotenberg engine added only if a persistent container is proven** on a real target (B3); SaaS rendering only on real demand. **Accept:** flipping `brandpdf_engine` to gotenberg needs no code change; loopback-only binding. | 5 |

**Critical path:** M0 is the only real risk gate — and within M0, the **short-page footer check (B1)** is the make-or-break. Everything downstream is packaging. Do not start the config spine (M4) until M0–M3 prove the loop on real BSTC quotations: the reference PDF is the spec; match it first, generalize second.

---

## 6. Decisions needed from the owner (with recommended defaults)

1. **Footer model** — fixed-position CSS band (pins on every page) vs accept footer-float-on-last-page for Phase 1. **Default: fixed band**; fall back only if M0 shows overlap.
2. **Phase-1 template source** — Jinja file in the app vs a Frappe Print Format we render. **Default: Jinja file** (fastest, owner has the proven HTML; move to DocType in Phase 2).
3. **Chromium acquisition** — reuse print_designer's binary vs user-cache `playwright install chromium`. **Default: whichever M0 proves first; prefer reuse, accept user-cache install (no root).**
4. **Arabic digits** — Western (1,234) vs Arabic-Indic (١٢٣٤). **Default: Western** with `<bdi>` isolation (clearer for bilingual quotations; revisit per brand).
5. **Print/Email integration depth (Phase 2)** — replace stock PDF globally vs only for mapped doctypes. **Default: mapped doctypes only** (least surprise, safest permissions).
6. **Licensing direction** — open-core+paid templates vs paid marketplace app vs SaaS. **Default: open-core engine + paid Pro tier; SaaS deferred** until a customer asks (MENA data-residency).
7. **Docker on the actual BSTC plan** — needed to keep the Gotenberg door open. **Default: assume unavailable on managed; confirm in M0 with a reboot+soak test before relying on it.**

---

## 7. Immediate next steps

1. **Run M0 on the real server, in this order:**
   - Scoped Chromium discovery: `find ~/.cache ~/frappe-bench /usr/lib/chromium* /opt -name 'chrome*' 2>/dev/null`.
   - `./env/bin/pip install playwright`; attempt render via the existing binary; if it fails, `./env/bin/playwright install chromium` (browser only, no root).
   - Render the owner's **proven HTML with a deliberately short last page**, options set by us (`prefer_css_page_size=True, print_background=True, margin=0, display_header_footer=False`), with the `document.fonts.ready` gate. **Confirm the footer pins on the short page.**
   - Record `docker version` result for the Phase-2 Gotenberg decision.
2. **Lock the footer model** based on M0 (recommended: fixed band).
3. **Scaffold the app** behind the engine abstraction (`bench new-app brandpdf`), then build M1 against Playwright.
4. **Do not** build config DocTypes until the BSTC Quotation loop is real and matching the reference PDF.

The relevant paths to create (all under the bench, not this repo): app root `~/frappe-bench/apps/brandpdf/`; template `brandpdf/brandpdf/templates/brandpdf/quotation_bstc.html`; engine `brandpdf/brandpdf/render/`; endpoint `brandpdf/brandpdf/api.py`; button `brandpdf/brandpdf/public/js/brandpdf_button.js`.