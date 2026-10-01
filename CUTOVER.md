# Cutover: `brandpdf` → `lumenpdf`

The app's internal id is **`lumenpdf`**. Everything users see was already "LumenPDF Studio";
this aligned the technical id, the DocType names, the desk route, and the asset paths.

The cutover is finished. No site runs the old `brandpdf` id any more, and the `master` branch
that carried it has been retired. Its last commit is kept as the tag `legacy/brandpdf-final`,
so the old id is still readable if it is ever needed. The rest of this file is the history of
how that was done, kept because the one rule below is still true for anyone renaming an app.

## ⚠ The one rule

**Never point an existing site's bench at the renamed code and hit Migrate.** Frappe registers
an app by its id; renamed code + an old registration = `ModuleNotFoundError: No module named
'brandpdf'`, which wedges *every* bench command (this is exactly what took the site down on
6 July). The rename is safe only as a **fresh install of the new id**.

That is why the two ids lived on separate branches while the cutover was in progress.

---

## A. New customers / marketplace (nothing special)

Register the repo on branch **`lumenpdf`**. They install a brand-new app:

```bash
bench get-app https://github.com/ma7mod7osam/LumenPDF-Studio --branch lumenpdf
bench --site <site> install-app lumenpdf
bench --site <site> migrate
```

No legacy anything. This is the path the marketplace listing should use.

---

## B. Your existing site (TemTemTech) — one-time migration

The old and new apps use **different DocType names** (`BrandPDF Template` →
`LumenPDF Template`), so saved formats do not carry over automatically. Export first.

**Do this on a quiet moment; budget ~30 minutes. Take a site backup first.**

### 1. Export what you want to keep
- Open the builder (`/app/brandpdf-builder`) → **File → Open / manage formats**.
- For **each** format you want to keep: Open it → **File → Export as .json** → save the file.
- Note down your **BrandPDF Settings** values per company (primary/secondary colour, font,
  header/footer banner image paths, footer registration text). A screenshot is enough.
- Note which format is the **default** for each doctype/company, and any report mappings.
- Your saved "My blocks" snippets are **not** exportable — note the few you care about and
  rebuild them after (they take seconds).

Uploaded images (`/files/...`) are untouched by all of this — banners and product photos stay.

### 2. Swap the app
On Frappe Cloud: Bench → Apps → **remove** `brandpdf`, then **Add App** from the repo on branch
`lumenpdf`, then **Deploy**, then install `lumenpdf` on the site.

Via bench:
```bash
bench --site <site> uninstall-app brandpdf     # asks for confirmation; drops its DocTypes
bench get-app https://github.com/ma7mod7osam/LumenPDF-Studio --branch lumenpdf
bench --site <site> install-app lumenpdf
bench --site <site> migrate
```

### 3. Restore
- Open `/app/lumenpdf-builder`.
- **LumenPDF Settings** → recreate the row(s) with the branding you noted.
- For each exported file: **File → Import from .json** → **✓ Save**.
- Re-set the defaults per doctype/company in **File → Open / manage formats**, and re-map
  reports (Save on a report format auto-activates it).
- Rebuild any block snippets.

### 4. Verify
- Print one quotation with **Download Branded PDF** → compare to a PDF from before.
- Open a report → the **Branded PDF** button → check landscape still works.
- `/api/method/lumenpdf.api.engine_diag` should report the engine as before.

### Rollback
If anything goes wrong: uninstall `lumenpdf`, re-add the app from the tag
**`legacy/brandpdf-final`** (still
`brandpdf`), install, migrate, re-import the same JSON files. Your exports work in either app —
the definition format is identical.

---

## What changed under the hood

| Before | After |
|---|---|
| app id `brandpdf` | `lumenpdf` |
| module `BrandPDF` | `LumenPDF` |
| DocTypes `BrandPDF Template/Settings/Mapping/Block/Snippet/...` | `LumenPDF ...` |
| desk route `/app/brandpdf-builder` | `/app/lumenpdf-builder` |
| assets `/assets/brandpdf/...` | `/assets/lumenpdf/...` |
| whitelisted methods `brandpdf.api.*` | `lumenpdf.api.*` |
| site_config `brandpdf_engine`, `brandpdf_chromium_path`, `brandpdf_feedback_email` | `lumenpdf_*` — **legacy keys still read** as a fallback, so you don't have to edit site_config |

Format definition JSON is unchanged, which is why export/import works across the rename.

---

## Branches

- **`lumenpdf`** is the default branch and the one the v14 and v15 marketplace listing builds
  from. All work lands here.
- **`version-16`** carries the same app with its own CI, because the marketplace serves v16
  from a separate source. Keep it in step with a merge, never a second edit: the two branches
  differ only in the workflow file and one README note.
- **`legacy/brandpdf-final`** is a tag, not a branch. It is the last commit of the retired
  `master`, the only place the old `brandpdf` id still exists.
