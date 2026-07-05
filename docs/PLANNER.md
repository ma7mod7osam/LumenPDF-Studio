The search confirms the technical landscape: Chromium is already on the server (print_designer ships it), `frappe_pdf`-style apps that call headless Chrome directly are a proven pattern, and the chromium binary path config has known gotchas. That's enough to commit to a decisive recommendation. The owner has already done the empirical verification that matters most.

Here is the plan.

---

# BrandPDF for ERPNext — Product & Architecture Plan

*A custom Frappe app that renders pixel-perfect, branded PDFs through a real Chromium engine, bypassing Frappe's PDF wrapper.*

---

## 0. The one-paragraph thesis

The owner has empirically proven the only fact that matters: **the target HTML renders perfectly in real Chromium, and the *only* thing breaking it in ERPNext is Frappe's generator layer hiding the `printToPDF` options.** Therefore the entire product reduces to one move — *take control of the rendering call ourselves and set the options Frappe hides* (`prefer_css_page_size`, `print_background`, `margin:0`, optional Chromium header/footer templates). Everything else (UI button, config DocTypes, productization) is packaging around that single capability. This is a low-technical-risk, high-polish-effort project. We are not inventing rendering; we are *un-wrapping* it.

---

## 1. Product vision & target users

### Vision
A drop-in Frappe app that makes ERPNext print formats look like they came from a design studio — full-bleed banners, exact margins, repeating headers/footers, modern CSS, clean RTL/Arabic — by rendering through a real browser engine instead of wkhtmltopdf, while staying upgrade-safe and configurable per business without touching code.

### The wedge (why anyone buys the first version)
"Make my ERPNext quotations/invoices look exactly like my brand, on every page, including Arabic — in 10 minutes, no code." This is a *visceral, universal* pain. Every ERPNext SMB that has tried to brand a document has hit the wkhtmltopdf wall and the print_designer margin/footer wall. The owner has lived 25 rounds of it; that lived pain is the product's credibility.

### Target users (in order of go-to-market priority)
1. **The owner's business (BSTC)** — Phase 1 customer-zero. Bilingual EN/AR, Bahrain, blue/navy brand. Proves the whole loop end-to-end on a real company.
2. **ERPNext SMBs in MENA / RTL markets** — the sharpest pain (Arabic + branding + wkhtmltopdf is the worst combination). This is the beachhead segment, not "all ERPNext."
3. **ERPNext implementation partners / freelancers** — they re-fight the branded-PDF battle on *every* client engagement. A reusable app that "just works" is a margin and time saver they'll pay for or resell. **Partners are the real distribution channel.**
4. **Design-conscious ERPNext SMBs globally** — anyone whose customer-facing PDFs are part of their brand (agencies, premium product sellers, contractors bidding on tenders).

### The broader product
Start as "branded PDF that actually works." Grow into **the document-presentation layer for ERPNext**: a template library, a branding settings hub, per-DocType template mapping, and a rendering service that the whole site routes print/email/attach through. The long-term framing: *"print_designer is the visual editor; BrandPDF is the engine that makes the output correct."* We are complementary to print_designer, not competing with its editor.

---

## 2. Scope split — MVP vs full product

### Phase 1 — MVP ("BSTC Quotation, end to end") — *opinionated, narrow, real*
The bar: BSTC can press one button on a Quotation and get the exact PDF the owner already proved renders perfectly in Chromium.

In scope:
- Custom app `brandpdf` installed on the site.
- One whitelisted endpoint: `brandpdf.api.download(doctype, name, template)` → permission check → Jinja render → real-Chromium PDF → stream as download.
- **One** hand-built Jinja template for Quotation (the proven `<table>`/`<thead>`/`<tfoot>` full-bleed structure), with BSTC branding hard-coded but pulled from a few config fields (logo/banner paths, colors, currency BHD, EN/AR).
- A native-feeling **"Download Branded PDF"** button injected on the Quotation form via client script / `doctype_js`.
- Rendering via the engine chosen in §3, calling Chromium with our own `printToPDF` options.
- Correct EN/AR, full-bleed header/footer repeating every page, blue table header, zebra rows, blue grand-total bar, correct margins. (Acceptance = visual diff against the owner's already-verified reference PDF.)

Explicitly OUT of Phase 1: multi-DocType, multi-company, a settings UI, template editing in-app, email/attach integration, licensing. Hard-code aggressively; prove the loop.

### Phase 2 — Full product ("configurable, multi-DocType, multi-company, sellable")
- **Branding Settings** DocType (per-company): banner/logo files, primary/navy hex, fonts, page size, margins, RTL toggle, footer text/registration numbers.
- **Template mapping** DocType: (DocType → template) so Sales Invoice, Delivery Note, Purchase Order, Statement, etc. each map to a template; multiple templates per DocType (e.g., "Quotation – Tender" vs "Quotation – Standard").
- **Template library**: a handful of high-quality starter templates the engine ships with; businesses clone + tweak.
- **Integration depth**: hook into the standard Print view, the Email dialog (attach branded PDF instead of stock), and **auto-attach-on-submit**; optional bulk print for list view.
- **Multi-company**: branding resolves by the document's company.
- **Onboarding wizard** + install via `bench get-app` / Frappe Cloud marketplace.
- **Licensing/metering hook** (see §5).
- Upgrade-safety hardening (no monkey-patching core; clean hooks only).

---

## 3. Engine decision — **Primary: Gotenberg. Fallback: Playwright (headless Chromium in-process).**

This is the one place I'll be most opinionated, and I'm going to *disagree slightly* with the instinct to reach for Playwright first — then hedge correctly.

### The decision
**Primary engine: Gotenberg** (containerized Chromium HTML→PDF microservice, called over HTTP).
**Named fallback: Playwright** driving the **Chromium binary that print_designer already installed** (no new browser download, in-process).
**Explicitly rejected as primary: WeasyPrint.**

### Why Gotenberg first (against the Cloudways constraints)

The decisive constraint is **Cloudways managed hosting: apt/root may be restricted.** That single fact reshapes the ranking:

- **Gotenberg** is a single Docker container exposing a clean HTTP API (`/forms/chromium/convert/html`) that accepts our HTML + assets and the exact knobs we need: `marginTop=0`, `printBackground=true`, `preferCssPageSize=true`, native header/footer HTML. It is *purpose-built* for exactly this "real Chromium, my options, over HTTP" pattern. The Frappe app stays pure-Python (just `requests.post`), so the app itself is trivially upgrade-safe and has **zero browser-management code** — no chromium path gotchas (the very `chromium_binary_path` vs `chromium_path` mismatch the search surfaced), no Playwright version drift, no zombie browser processes in the bench. The rendering concern is fully isolated behind a URL. **For productization this is the killer feature**: the same app works on Frappe Cloud, self-hosted, or Cloudways by just pointing `BRANDPDF_RENDER_URL` at a container — and we can later run that container as a **shared SaaS rendering endpoint** (see §5, the SaaS option falls out for free).
- The cost: it's a second moving part (a container). On Cloudways you'd run it as a Docker container on the same server or a small side VPS. If Docker is genuinely unavailable on the managed plan, that's the trigger to fall back.

### Why Playwright is the fallback, not the primary
Playwright gives the **best raw fidelity and is "already paid for"** — Chromium + system libs are confirmed present because print_designer's chrome generator runs. So `playwright install chromium` may even be skippable by pointing at the existing binary. It is the right call **if Docker is unavailable** or if we want zero extra infrastructure. Why not primary: it couples PDF rendering *into the Frappe Python process* (browser lifecycle, memory, concurrency, version pinning all become the app's problem and a per-upgrade risk), and it's harder to productize cleanly across heterogeneous customer hosts. It's a fantastic fallback precisely because the environment already proves it can work — but it makes the *product* heavier. **For a single-site owner deployment, Playwright-on-the-existing-Chromium is actually the fastest path to a working Phase 1**; for a *sellable product*, Gotenberg wins. We resolve this in the roadmap by building Phase 1 against Playwright if Docker setup blocks us, behind an engine abstraction, so the choice is reversible.

### Why WeasyPrint is rejected
WeasyPrint is pure-Python and lovely for paged media, but it is **not Chromium** — it has its own CSS engine. The owner's entire proof rests on "this exact HTML renders perfectly *in Chromium*." Switching to WeasyPrint throws away the verified artifact and reopens the CSS-compat fight (flexbox, `-webkit-print-color-adjust`, web-font quirks, RTL edge cases). Using a non-Chromium engine would mean re-validating everything. Not worth it when Chromium is already on the box. Keep it nowhere in the stack.

### Non-negotiable: an engine abstraction
Define a one-method internal interface — `render(html, options) -> pdf_bytes` — with `GotenbergRenderer` and `PlaywrightRenderer` implementations selected by site config (`brandpdf_engine`). This makes the primary/fallback choice a config flag, protects against any single engine surprise, and is itself a productization asset ("works with whatever Chromium you have").

---

## 4. System design (high level)

### Data flow (the happy path)
```
User clicks "Download Branded PDF" on Quotation form
        │
        ▼
client script → frappe.call("brandpdf.api.download", {doctype, name, template})
        │
        ▼  (server, whitelisted)
1. frappe.get_doc(doctype, name)        ← permission check via has_permission(read)
2. resolve branding   (company → Branding Settings)
3. resolve template   (doctype → Template Map → Jinja file/Print Format)
4. render Jinja → HTML  (assets = absolute file URLs / inlined for portability)
        │
        ▼
5. renderer.render(html, {margin:0, print_background:true,
                          prefer_css_page_size:true, header/footer})
        │  Gotenberg HTTP   ── or ──  Playwright in-process  (engine abstraction)
        ▼
6. pdf_bytes  → frappe.response (download)  AND/OR  attach to document (File)
```

### Where rendering happens
Outside the Frappe PDF pipeline entirely. We never call `frappe.utils.pdf.get_pdf` (wkhtmltopdf) or the print_designer chrome generator. We own the `printToPDF` options. This is the whole point of the project and the reason it succeeds where 25 rounds failed.

### Templates & branding configuration
- **Templates** are Jinja (Phase 1: a file in the app; Phase 2: stored in a DocType so businesses edit in-app, or mapped to a Print Format whose HTML we render through *our* engine — reusing print_designer's editor for layout but our engine for output is the elegant long-term play).
- **Branding** resolves at render time from a per-company **Branding Settings** record. The template references `branding.primary`, `branding.banner_header_url`, `branding.font`, etc. — so the *same* template re-skins per company with no code change.
- **Assets**: banner PNGs already in `/files/`. For Gotenberg we either pass them in the multipart form or use absolute URLs the container can reach; for Playwright, absolute `file://` or site URLs. Inlining as base64 is the safest portability default for the product.

### Integration surface
- **Button** (Phase 1): `doctype_js` / client script adds a primary action; native look via `frm.add_custom_button`.
- **Print view** (Phase 2): register our renderer so the standard Print/PDF button routes through us for mapped DocTypes.
- **Email** (Phase 2): hook the communication/email flow to attach our branded PDF instead of the stock one.
- **Auto-attach on submit** (Phase 2): `on_submit` hook renders + attaches the branded PDF as a File on the document.
- **Bulk** (Phase 2): list-view bulk action → merge per-doc PDFs (the PDF merge tooling for this is trivial and well-trodden).

### Upgrade-safety rules (productization-critical)
- No monkey-patching of Frappe/ERPNext core. Only `hooks.py` (doctype_js, override where Frappe officially supports it, scheduled/email hooks).
- All config in our own DocTypes + site config keys namespaced `brandpdf_*`.
- Engine isolated behind the abstraction so a Chromium/Playwright/Gotenberg bump never touches business code.

---

## 5. Productization

### How a business configures branding + templates
A three-DocType spine (introduced in Phase 2):
1. **BrandPDF Settings** (per company): banners, logo, colors (primary/navy hex), fonts, page size, margins, RTL toggle, footer registration text, default engine.
2. **BrandPDF Template** (the template library): name, target DocType, Jinja body (or link to a Print Format), language(s). Ships with curated starters; businesses clone and edit.
3. **BrandPDF Mapping**: (DocType + optional condition) → Template + Branding. This is what makes it "no code each time" — onboarding is *filling forms*, not writing Python.

Onboarding wizard: upload banners → pick colors/fonts → choose a starter template per DocType → click "Preview" → done. The owner's BSTC setup becomes the first showcase/demo template.

### Packaging & install
- Standard Frappe app: `bench get-app brandpdf && bench --site x install-app brandpdf`.
- Plus a one-line Gotenberg bring-up (docker compose snippet shipped in the repo) or a "use Playwright (no container)" install path.
- List on **Frappe Cloud Marketplace** once Phase 2 is stable — that's the discovery channel for the broader market.

### Licensing / pricing — options, with a recommendation
1. **Open-core + paid support/setup** — app is open source (great for adoption + partner trust), monetize done-for-you template design, setup, and priority support. *Lowest friction, best for credibility, weakest recurring revenue.*
2. **Per-site commercial license** — paid app on the marketplace, license key checked at install/runtime. *Clean, conventional for ERPNext; piracy-leaky but normal for the ecosystem.*
3. **SaaS rendering service** — the app is free/cheap, but rendering calls go to *our* hosted Gotenberg endpoint, metered per PDF. *This is why Gotenberg-first is strategically smart: the architecture already produces a meterable rendering boundary.* Best recurring revenue, but adds a data-sensitivity concern (customer documents transit our service — needs a clear privacy story and a self-host option for those who refuse).
4. **Marketplace paid app + tiers** (Free: 1 template; Pro: unlimited + multi-company + email/attach; Agency: white-label for partners).

**Recommended posture:** *Open-core for the engine/abstraction (drives adoption and partner goodwill) + a paid "Pro" tier for the configuration spine, template library, and integrations (per-site license via marketplace), with the SaaS rendering endpoint as an optional convenience for those who can't run a container.* Lead with #1+#2; keep #3's door open because the design hands it to us for free. Partners get a white-label/agency tier — they are the distribution.

### Support & maintenance posture
- Pin engine versions; test against each ERPNext v15 point release before declaring compatibility.
- A visual regression suite (render the showcase templates, diff against golden PDFs) is the single highest-leverage maintenance investment — it's also the QA gate the owner already does manually.
- Public template gallery + docs site; partner-facing white-label guide.

---

## 6. Risks & open questions

**Risks**
- **Cloudways Docker availability** — the load-bearing assumption for Gotenberg-primary. *Mitigation:* engine abstraction + Playwright fallback on the already-present Chromium; verify Docker on the actual plan in Roadmap M0 before committing infra.
- **Asset reachability across engines** — Gotenberg-in-a-container may not see `/files/` URLs the same way the bench does. *Mitigation:* base64-inline assets (already proven to render); make inlining the default.
- **Concurrency / memory** (Playwright path) — headless Chromium is heavy under load. *Mitigation:* Gotenberg handles this natively; for Playwright, a small queue/limit.
- **Arabic/RTL edge cases** in real documents beyond the proven sample (mixed LTR numbers in RTL lines, long product names). *Mitigation:* test with real BSTC data early.
- **SaaS data sensitivity** — customer invoices through our endpoint. *Mitigation:* self-host option always available; the SaaS path is opt-in.
- **print_designer coexistence** — both want Chromium; config-key clash is documented. *Mitigation:* we don't depend on print_designer's generator at all; we manage our own engine config under `brandpdf_*`. Optionally *reuse* its editor later (read its Print Format HTML, render through our engine).

**Open questions (for the Executer / owner)**
1. Is Docker available on the BSTC Cloudways plan? (Decides Gotenberg vs Playwright for Phase 1 infra.)
2. Phase 1 template source of truth: a Jinja file in the app, or a Frappe Print Format whose HTML we render? (Affects whether non-devs can edit early.)
3. Do we want to *reuse print_designer as the visual editor* long-term, or build/borrow our own template editing? (Big architecture fork for Phase 2.)
4. Email/attach: replace stock attachment globally, or only for mapped DocTypes? (Permissions + least-surprise.)
5. Licensing direction the owner actually wants (open-core vs paid marketplace vs SaaS) — shapes how much license/metering plumbing Phase 2 needs.

---

## 7. Phased roadmap (milestones + relative effort)

Effort is **relative** (1 = a focused day-ish unit), not calendar time.

| Milestone | Goal | Deliverable / exit criteria | Effort |
|---|---|---|---|
| **M0 — Spike & engine pick** | De-risk the environment | On the real server: confirm Docker (Gotenberg) *or* reach the existing Chromium via Playwright; render the owner's proven HTML to a correct PDF *from the server*, options set by us. Pick primary engine. | **2** |
| **M1 — MVP loop (Phase 1)** | BSTC Quotation, one button | `brandpdf` app + whitelisted `download` endpoint (with permission check) + engine abstraction + one Quotation Jinja template + form button. Output visually matches the owner's reference PDF (full-bleed, repeating header/footer, blue header, zebra, total bar, correct margins, clean EN/AR). | **5** |
| **M2 — Harden Phase 1** | Production-trustworthy for BSTC | Asset inlining, error handling, real-data Arabic/RTL testing, attach-to-doc option, basic golden-PDF regression test. BSTC uses it for real quotations. | **3** |
| **M3 — Config spine (Phase 2 start)** | "No code each time" | BrandPDF Settings + Template + Mapping DocTypes; branding resolves per company; multiple templates per DocType. Re-skin BSTC purely via config. | **6** |
| **M4 — Multi-DocType + integrations** | Beyond Quotation | Sales Invoice + ≥1 more template; hook Print view + Email attach + auto-attach-on-submit; optional bulk. | **6** |
| **M5 — Productize & package** | Sellable | Onboarding wizard, starter template library, docs site, install paths (Gotenberg compose + Playwright), upgrade-safety pass, visual regression suite. | **6** |
| **M6 — Go-to-market** | Reach other businesses | Marketplace listing, pricing/licensing implementation (per chosen model), partner/white-label tier, SaaS rendering endpoint *if* pursued. | **5** |

**Critical path & advice for the Executer:** M0 is the only real risk gate — everything downstream is packaging. Build M1 *behind the engine abstraction* even if you start on Playwright, so the Gotenberg/Playwright decision stays reversible. Resist building the config spine (M3) before M1+M2 prove the loop on real BSTC quotations; the owner's lived pain is the spec — match the already-verified reference PDF first, generalize second.

---

### Sources
- [frappe/print_designer (GitHub)](https://github.com/frappe/print_designer) — the chrome generator that confirms Chromium is on the server.
- [Ponnusamy1-V/frappe-pdf (GitHub)](https://github.com/Ponnusamy1-V/frappe-pdf) — proven precedent: a Frappe app rendering PDF via headless google-chrome, our exact pattern.
- [Chrome PDF Generator issues — Frappe Forum](https://discuss.frappe.io/t/chrome-pdf-generator-issues-print-designer/149158) and [print_designer issue #437](https://github.com/frappe/print_designer/issues/437) — the `chromium_binary_path` vs `chromium_path` config gotcha (argument for isolating engine config under `brandpdf_*`).
- [Having Print Designer installed breaks pdf generation via chromium #1821](https://github.com/frappe/frappe_docker/issues/1821) — print_designer/Chromium coexistence pitfalls (why we manage our own engine).
- [Guide to Frappe PDF Generation & Fixing wkhtmltopdf — Sabbirz](https://www.sabbirz.com/blog/guide-to-frappe-pdf-generation-fixing-wkhtmltopdf-meta) — corroborates the wkhtmltopdf limitations driving this project.