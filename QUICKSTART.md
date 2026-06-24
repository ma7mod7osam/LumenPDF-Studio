# BrandPDF — Quick Start

**Forward this whole page to whoever manages your ERPNext server** (or follow it yourself).
It installs the BrandPDF add-on so a "Download Branded PDF" button appears on Quotations.

It needs: SSH / bench access to the ERPNext **v15** site. Chromium is already on the server
(Print Designer installed it), so no root/apt is required.

---

## 1. Copy the app folder onto the server
Put this whole `BrandPDF-ERPNext` folder somewhere on the server, e.g. `/home/frappe/BrandPDF-ERPNext`.
(Or push it to a private git repo and use that URL in step 3.)

## 2. Quick sanity test (5 min, optional but recommended)
```bash
cd ~/frappe-bench
./env/bin/pip install -r /home/frappe/BrandPDF-ERPNext/m0-spike/requirements.txt
./env/bin/playwright install chromium
./env/bin/python /home/frappe/BrandPDF-ERPNext/m0-spike/m0_spike.py
```
This writes 3 sample PDFs next to the script. Open them — the header should sit at the top,
the footer at the bottom, and Arabic should look correct. If yes, the engine works here.

## 3. Install the app
```bash
cd ~/frappe-bench
bench get-app /home/frappe/BrandPDF-ERPNext
./env/bin/playwright install chromium          # if step 2 was skipped
bench --site <your-site> install-app brandpdf
bench build --app brandpdf
bench --site <your-site> migrate
bench restart
```

## 4. Upload the two banner images (once)
In ERPNext, upload `2Header.png` and `2Footer.png`, and make each File **Public**
(open the File record, untick "Private"). These are the header/footer banners.

## 5. Use it
Open any **Quotation** → click **Download Branded PDF**. You get the branded PDF.

---

## (Later) Turn on the no-code config screens
Optional — lets you set logo/colors/templates from a form instead of code:
```bash
bench set-config -g developer_mode 1 && bench restart
bench --site <your-site> execute brandpdf.setup.install_config.run
bench --site <your-site> migrate
```

## If something looks wrong
- Banners missing → the image Files aren't set to Public (step 4).
- Button missing → run `bench build --app brandpdf` and hard-refresh the browser.
- Render error → check **Error Log** in ERPNext.
- Full details for a developer: `docs/INSTALL.md`, `docs/PLAN.md`.

## What this is / isn't (yet)
This is the **engine + the button** — reliable branded PDFs. The **visual "build your own
format" designer** is the next phase; it plugs into this same engine. You don't need it to
start printing branded quotations today.
