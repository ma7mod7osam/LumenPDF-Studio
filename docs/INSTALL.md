# BrandPDF — Install & Run

Target: ERPNext/Frappe **v15** on Cloudways (SSH + bench access). Chromium and its system
libs are already present (print_designer's chrome generator runs), so no `apt`/root is needed.

## 0. Run M0 first (do not skip)
The whole design hinges on one validation (PLAN §7). On the server:

```bash
cd ~/frappe-bench
./env/bin/pip install playwright pymupdf
./env/bin/playwright install chromium          # browser only, no root
./env/bin/python /path/to/BrandPDF-ERPNext/m0-spike/m0_spike.py
```
Open the three PDFs it writes. Confirm: footer pins on the short page; Arabic renders; a
Chromium was driven without root. If Playwright won't use the system Chromium, set
`BRANDPDF_CHROMIUM=/path/to/chrome` and re-run. **Only proceed once M0 passes.**

## 1. Install the app
```bash
cd ~/frappe-bench
bench get-app brandpdf /path/to/BrandPDF-ERPNext/brandpdf      # or a git remote
./env/bin/pip install playwright requests
./env/bin/playwright install chromium                          # if not already from M0
bench --site <your-site> install-app brandpdf
bench build --app brandpdf
bench --site <your-site> migrate
bench restart
```

## 2. Configure (site_config.json)
`~/frappe-bench/sites/<your-site>/site_config.json`:
```json
{
  "brandpdf_engine": "playwright",
  "brandpdf_chromium_path": null,
  "brandpdf_render_url": "http://localhost:3000"
}
```
- `brandpdf_chromium_path`: set to the system Chromium path if M0 showed Playwright needs it.
- Switch `brandpdf_engine` to `"gotenberg"` only after a container is proven on your plan.

## 3. Make the banner images Public
Upload `2Header.png` and `2Footer.png` and ensure the File records are **Public**
(they resolve to `/files/...` and get base64-inlined at render time).

## 4. Use it
Open a **Quotation** → **Download Branded PDF**. The button enqueues a render on the
`long` queue, polls, and opens the private PDF when ready.

## 5. Requirements / notes
- A **`long` queue worker** must be running (default in `bench start` / production supervisor).
- Rendering is **serialized through the background worker** — one Chromium at a time, so a
  managed box won't OOM under concurrent clicks.
- Generated PDFs are **private Files** attached to the document, auto-cleaned daily.
- Engine swap (Playwright ↔ Gotenberg) is a `site_config` change — no code edits.

## Troubleshooting
- **Blank/missing banners** → the File isn't Public, or the path in branding is wrong.
- **`playwright` import error in the worker** → installed into the wrong env; use `./env/bin/pip`.
- **Footer not at the bottom on a multi-page quote** → known v1 limit (see PLAN B1);
  the native-footer upgrade is the fix; validate via `m0_nativefooter_long.pdf` from M0.
- **Render errors** → check **Error Log** (the job logs there; the UI shows a generic message).
