# BrandPDF for ERPNext

A custom Frappe/ERPNext v15 app that renders pixel-perfect, branded PDFs (Quotations first, then Sales Invoices and beyond) through a **real Chromium engine** — bypassing Frappe's PDF wrapper, which hides the `printToPDF` options needed for full-bleed banners, exact margins, reliable backgrounds, and clean RTL/Arabic.

> **Core insight (already proven):** the target HTML renders perfectly in real Chromium. The only thing breaking it in ERPNext is Frappe's generator layer hiding the rendering options. So this is an *un-wrapping* project, not a rendering-research project.

## Phase 1 customer-zero
**BSTC** — Building Solutions Trading & Contracting W.L.L (Bahrain, bilingual EN/AR, BHD, blue `#1C75BC` / navy `#1A1E2A`). One button on a Quotation → the exact branded PDF.

## Engine decision
- **Phase 1: Playwright** driving the Chromium already on the server (installed by print_designer). In-process, no new infra. Chosen over Gotenberg because Docker is unreliable on managed Cloudways.
- Behind a `render(html, options) -> bytes` abstraction, so **Gotenberg stays a zero-rewrite swap** for later.
- WeasyPrint rejected (not Chromium → throws away the verified proof).

## Repo layout
- `docs/PLAN.md` — the approved, consolidated build plan (read this first).
- `docs/QA-REVIEW.md` — adversarial review: blockers, highs, fixes.
- `docs/PLANNER.md`, `docs/EXECUTER.md` — raw role outputs.
- `reference/quotation-reference.html` — the Chromium-verified quotation HTML to build the template from.
- `m0-spike/` — the de-risking spike (see below).

## The one thing that de-risks everything: M0
Before any app code, run the **M0 spike** on the real server:
1. Find the existing Chromium; get Playwright to drive it without root.
2. Render the verified HTML **with a deliberately short last page** and confirm the **footer pins to the bottom** (the load-bearing check).
3. Confirm `document.fonts.ready` gating + Arabic render correctly.

If M0 passes, the rest is packaging.

## Continuing in a fresh session
This folder was set up from a session rooted elsewhere. For the build, open Claude Code **in this folder** so it becomes the project root with its own memory. Start by reading `docs/PLAN.md` §7 (Immediate next steps).
