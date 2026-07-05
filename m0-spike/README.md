# M0 spike — the one thing that de-risks everything

Run `m0_spike.py` ON THE SERVER (bench env) before trusting the app. It validates:

1. Playwright can drive a Chromium **without root**.
2. The committed footer model (`<thead>`/`<tfoot>` + `height:100%`) **pins the footer** on a
   short single page; and it renders a **native-footer** variant so you can decide whether
   multi-page quotations need that upgrade.
3. Fonts load (`document.fonts.ready`) and **Arabic** renders.

```bash
cd ~/frappe-bench
./env/bin/pip install playwright pymupdf
./env/bin/playwright install chromium
./env/bin/python <path>/m0-spike/m0_spike.py
# optional, if Playwright needs the existing binary:
LUMENPDF_CHROMIUM=/path/to/chrome ./env/bin/python <path>/m0-spike/m0_spike.py
```

Outputs three PDFs next to the script. **Open them** — measurement alone can mislead for
fixed/native footers (vector vs raster), so judge visually. Whichever footer behavior you
want locks PLAN decision #1.
