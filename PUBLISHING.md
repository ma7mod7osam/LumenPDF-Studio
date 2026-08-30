# Publishing LumenPDF Studio to the Frappe Cloud Marketplace

## Already done in this repo (v1.1.0)

- [x] Semantic version `1.1.0` (`lumenpdf/__init__.py`), git tags `v1.0.0` / `v1.1.0`.
- [x] MIT `license.txt`; `pyproject.toml` metadata; no hard pip dependencies
      (playwright/gotenberg are optional extras).
- [x] Marketplace-grade `README.md` (the marketplace listing imports it as the description).
- [x] Product logo — the "Page Blocks" mark (`lumenpdf/public/images/lumenpdf-logo.svg`, wired
      via `app_logo_url`; marketplace PNGs = `lumenpdf-logo-300.png` / `-512.png` from the
      logo kit, in Downloads).
- [x] No client-specific content on fresh installs: neutral `DEFAULT_BRANDING` (no hardcoded
      banner files, RTL off), generic starter seed ("Quotation - Starter", guarded for
      non-ERPNext sites), generic sample text in the builder.
- [x] Internal planning docs / spikes removed from the repo tree.

## Portal steps (you do these on frappecloud.com)

1. **Publisher account**: Frappe Cloud dashboard → Marketplace → Become a Publisher
   (one-time; set publisher display name, e.g. "BSTC" or "Lumen").
2. **Add the app**: Marketplace → My Apps → Add App → pick the GitHub repo
   `ma7mod7osam/LumenPDF-Studio`, branch `master` (grant the Frappe Cloud GitHub app access
   to the repo if not already).
3. **Listing**: title "LumenPDF Studio", category (likely "ERPNext" / "Utilities"), the
   description auto-imports from README — review it; upload the logo (a 300×300 PNG export of
   `lumenpdf-logo.svg` works) and **3–5 screenshots**:
   - the builder canvas with a quotation format open,
   - the Templates gallery,
   - report mode (General Ledger, landscape),
   - a finished branded PDF,
   - the Formats manager.
4. **Support links**: website / support email (support@bstc-bh.com) / docs link (the README).
5. **Pricing**: free, or set plans (Marketplace supports paid apps with revenue share).
6. **Submit for review.** Frappe's team checks that it installs cleanly on a fresh bench and
   that the listing is honest. The `after_install` + `after_migrate` self-configuration means a plain
   `install-app lumenpdf` works with zero manual steps — that's the main functional check.
7. After approval, each release = push to `master` + a new git tag; the marketplace builds from
   the branch you registered.

## Things to know / decide

- **Repo visibility**: the marketplace can build from a private repo via the GitHub app grant,
  but a public repo builds trust (and the README renders on GitHub). If you make it public,
  remember the *git history* still contains the old internal docs — that's fine, just be aware.
- **Your own site after this release**: `DEFAULT_BRANDING` no longer hardcodes
  `/files/2Header.png` / `2Footer.png`. If any of your documents relied on that implicit
  fallback, set the banners properly in **LumenPDF Settings** (one row for your company) —
  that's the supported mechanism and survives upgrades.
- **Naming**: the marketplace lists the app by `app_title` ("LumenPDF Studio"); the internal
  `app_name` stays `lumenpdf` and must never change (installed sites depend on it).
- **Screenshots tip**: take them on a clean demo site (fresh bench + demo data), not the
  TemTemTech test site, so no real business data appears in the listing.
