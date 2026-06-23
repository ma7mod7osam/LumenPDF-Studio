# BrandPDF (Frappe app)

Renders pixel-perfect, branded PDFs for ERPNext documents through a **real Chromium engine**
(Playwright by default, Gotenberg optional) — bypassing Frappe's PDF wrapper so you control
`printToPDF` (full-bleed margins, backgrounds, repeating banners, clean RTL/Arabic).

See the project root `../docs/PLAN.md` for the full design, and `../docs/INSTALL.md` to install.

## Quick install
```bash
cd ~/frappe-bench
bench get-app brandpdf /path/to/brandpdf      # or your git remote
./env/bin/pip install playwright requests
./env/bin/playwright install chromium          # browser only; no root needed
bench --site <site> install-app brandpdf
bench build --app brandpdf
bench --site <site> migrate
bench restart                                  # ensure a 'long' queue worker is running
```

Open a Quotation → **Download Branded PDF**.

## Engine config (site_config.json)
```json
{
  "brandpdf_engine": "playwright",            // or "gotenberg"
  "brandpdf_chromium_path": null,              // optional explicit chromium binary
  "brandpdf_render_url": "http://localhost:3000" // gotenberg only
}
```
