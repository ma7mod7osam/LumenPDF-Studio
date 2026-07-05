#!/usr/bin/env python3
"""
BrandPDF — M0 de-risking spike.  Run ON THE REAL SERVER inside the bench env.

Validates the three load-bearing questions from docs/PLAN.md before app code matters:
  1. Can Playwright drive a Chromium on this box WITHOUT root?
  2. Does the committed footer model pin the footer to the bottom?
  3. Do fonts load (document.fonts.ready gate) + does Arabic render?

FOOTER MODEL (decided in local testing with real Chromium):
  <thead> header (full-bleed, repeats every page) + <tfoot> footer + height:100% on the
  page table. This VISIBLY pins the footer to the bottom on a single page (the common
  quotation case). NOTE: on a MULTI-page doc the last (short) page's footer follows the
  content rather than the absolute bottom — a known v1 limitation. The future upgrade is a
  native Chromium footer_template; this spike also renders that so you can compare on-server.

Usage:
    ./env/bin/python m0_spike.py
    # if missing:  ./env/bin/pip install playwright pymupdf  &&  ./env/bin/playwright install chromium

Outputs (next to this file): m0_threadtfoot_short.pdf, m0_threadtfoot_long.pdf, m0_nativefooter_long.pdf
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FOOTER_MM = 36

CSS = """
  html, body { margin:0 !important; padding:0 !important; height:100%; }
  @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&family=Montserrat:wght@400;600;700;800&display=swap');
  .bs-content { font-family:'Montserrat',Arial,sans-serif; color:#1A1E2A; font-size:8.5pt; padding:6mm 14mm; }
  .bs-title { font-size:22pt; font-weight:800; margin:0 0 3mm; }
  .bs-title-ar { font-family:'Cairo',Tahoma,sans-serif; font-size:12pt; font-weight:600; color:#1C75BC; direction:rtl; margin-bottom:4mm; }
  table.bs-items { width:100%; border-collapse:collapse; table-layout:fixed; }
  table.bs-items thead th { background:#1C75BC !important; color:#fff !important; font-size:7.5pt; padding:6px 8px; text-align:left; -webkit-print-color-adjust:exact; }
  table.bs-items td { padding:6px 8px; border-bottom:1px solid #cfe5f6; font-size:8pt; }
  table.bs-items tr { break-inside:avoid; }
  .hdr { width:100%; height:%dmm; background:#1C75BC; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; -webkit-print-color-adjust:exact; }
  .ftr { width:100%; height:%dmm; background:#1A1E2A; color:#fff; display:flex; align-items:center; justify-content:center; -webkit-print-color-adjust:exact; }
""" % (FOOTER_MM, FOOTER_MM)

def _rows(n):
    return "".join(f"<tr><td>{i}</td><td>Sample Product Item {i}</td><td>{i} Nos</td><td>BHD {i*3.5:.3f}</td><td>BHD {i*21:.3f}</td></tr>" for i in range(1, n + 1))

def _body(n):
    return (f'<div class="bs-content"><div class="bs-title">QUOTATION</div>'
            f'<div class="bs-title-ar">عرض سعر — اختبار ١٢٣٤</div>'
            f'<table class="bs-items"><thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th></tr></thead>'
            f'<tbody>{_rows(n)}</tbody></table></div>')

def thead_tfoot(n):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  @page {{ size:A4; margin:0; }} {CSS}
  table.page {{ width:100%; height:100%; border-collapse:collapse; }}
  table.page > thead > tr > td, table.page > tfoot > tr > td, table.page > tbody > tr > td {{ padding:0; border:0; }}
  table.page > tbody > tr > td {{ vertical-align:top; height:100%; }}
</style></head><body>
<table class="page">
  <thead><tr><td><div class="hdr">HEADER (repeats)</div></td></tr></thead>
  <tfoot><tr><td><div class="ftr">FOOTER (pinned on single page)</div></td></tr></tfoot>
  <tbody><tr><td>{_body(n)}</td></tr></tbody>
</table></body></html>"""

def native_footer_body(n):
    # header still via thead; footer supplied to page.pdf() as footer_template (see render_native)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  @page {{ size:A4; }} {CSS}
  table.page {{ width:100%; border-collapse:collapse; }}
  table.page > thead > tr > td, table.page > tbody > tr > td {{ padding:0; border:0; }}
</style></head><body>
<table class="page">
  <thead><tr><td><div class="hdr">HEADER (repeats)</div></td></tr></thead>
  <tbody><tr><td>{_body(n)}</td></tr></tbody>
</table></body></html>"""

NATIVE_FOOTER_TEMPLATE = (
    '<div style="width:100%; height:%dmm; background:#1A1E2A; color:#fff; '
    'font-size:9px; display:flex; align-items:center; justify-content:center; '
    '-webkit-print-color-adjust:exact;">FOOTER (native template, every page)</div>' % FOOTER_MM
)

def discover_chromium():
    print("== Chromium discovery ==")
    found = []
    for base in ("~/.cache", "~/frappe-bench", "/usr/lib", "/opt", "/usr/bin"):
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        try:
            out = subprocess.run(["find", base, "-maxdepth", "6", "-type", "f",
                "(", "-name", "chrome", "-o", "-name", "chromium", "-o", "-name", "chrome-headless-shell", ")"],
                capture_output=True, text=True, timeout=30)
            found += [l.strip() for l in out.stdout.splitlines() if l.strip()]
        except Exception as e:
            print("  (skip", base, e, ")")
    for f in found:
        print("  found:", f)
    if not found:
        print("  none found by search (Playwright's own chromium may still be installed)")
    return found

def _launch(p, exe):
    kw = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if exe:
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)

def render_css(html, out, exe):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p, exe); pg = b.new_page()
        pg.set_content(html, wait_until="load")
        try: pg.evaluate("async () => { if (document.fonts) { await document.fonts.ready; } }")
        except Exception as e: print("  (fonts.ready warn:", e, ")")
        pg.pdf(path=out, format="A4", print_background=True, prefer_css_page_size=True,
               display_header_footer=False, margin={"top":"0","bottom":"0","left":"0","right":"0"})
        b.close()

def render_native(html, out, exe):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p, exe); pg = b.new_page()
        pg.set_content(html, wait_until="load")
        try: pg.evaluate("async () => { if (document.fonts) { await document.fonts.ready; } }")
        except Exception as e: print("  (fonts.ready warn:", e, ")")
        pg.pdf(path=out, format="A4", print_background=True,
               display_header_footer=True, header_template="<span></span>",
               footer_template=NATIVE_FOOTER_TEMPLATE,
               margin={"top":"0","bottom":f"{FOOTER_MM}mm","left":"0","right":"0"})
        b.close()

def report(pdf):
    try: import fitz
    except Exception: return "  (pip install pymupdf to auto-measure; else open the PDF)"
    d = fitz.open(pdf); lines = []
    for i in range(d.page_count):
        pg = d[i]; ph = pg.rect.height
        bands = [dr["rect"] for dr in pg.get_drawings() if dr.get("fill") and max(dr["fill"]) < 0.2]
        f = max(bands, key=lambda r: r.y1) if bands else None
        lines.append(f"    page {i}: footer band y1={round(f.y1) if f else '-'} of {round(ph)} (gap {round(ph-f.y1) if f else '-'})")
    return "\n".join(lines) + "\n    NOTE: verify visually too — fixed/native footers can mis-measure vs raster."

def main():
    try: import playwright  # noqa
    except Exception:
        print("Playwright missing. Run (no root needed; system libs already present):")
        print("  ./env/bin/pip install playwright pymupdf")
        print("  ./env/bin/playwright install chromium")
        sys.exit(1)
    discover_chromium()
    exe = os.environ.get("BRANDPDF_CHROMIUM")
    if exe: print("== using BRANDPDF_CHROMIUM:", exe)
    jobs = [
        ("m0_threadtfoot_short.pdf", lambda o: render_css(thead_tfoot(4), o, exe)),
        ("m0_threadtfoot_long.pdf",  lambda o: render_css(thead_tfoot(45), o, exe)),
        ("m0_nativefooter_long.pdf", lambda o: render_native(native_footer_body(45), o, exe)),
    ]
    for name, fn in jobs:
        out = os.path.join(HERE, name)
        print("\n== Rendering", name, "==")
        fn(out); print("  ->", out); print(report(out))
    print("\n== VERDICT ==")
    print("Open all three. thead/tfoot pins the footer on the SHORT single page (primary model).")
    print("On the LONG doc, compare thead/tfoot (last page footer floats) vs native-footer (pins every page)")
    print("to decide whether multi-page quotations need the native-footer upgrade. That locks PLAN decision #1.")

if __name__ == "__main__":
    main()
