# Phase 2 — Config DocTypes (the no-code spine)

> **These are now built programmatically** (no hand-written JSON) by
> `brandpdf/setup/install_config.py`. Run it on the bench after M0–M3 prove the BSTC loop:
>
> ```bash
> bench set-config -g developer_mode 1 && bench restart
> bench --site <site> execute brandpdf.setup.install_config.run
> bench --site <site> migrate          # then commit the generated brandpdf/brandpdf/doctype/* JSON
> ```
> Can't enable developer_mode? Create Custom DocTypes instead:
> `bench --site <site> execute brandpdf.setup.install_config.run --kwargs "{'as_custom': True}"`
>
> The creator also **seeds** a standard "Quotation - BSTC" template + a Quotation mapping, so
> the app routes through the spine immediately. `brandpdf/resolver.py` already reads these
> (branding by `doc.company`, template via mapping) with graceful fallback to Phase-1 defaults.

The field spec each DocType is built from (kept here as the source of truth):

---

## 1. BrandPDF Settings  (one per Company; `is_single = 0`)
Branding resolved by `doc.company`, with `render_html.DEFAULT_BRANDING` as fallback.

| Field | Type | Notes |
|---|---|---|
| company | Link → Company | unique |
| header_image | Attach Image | full-bleed top banner |
| footer_image | Attach Image | full-bleed bottom banner |
| primary_color | Data | hex, regex-validated `^#[0-9A-Fa-f]{6}$` |
| secondary_color | Data | hex (navy) |
| font_family | Select | bundled fonts only |
| page_size | Select | A4 (default) / Letter |
| rtl | Check | bilingual / Arabic |
| footer_registration_text | Small Text | CR / VAT line (optional) |
| default_engine | Select | playwright / gotenberg |

Permissions: read = All; write = System Manager. Missing record → safe default branding (never throw).

## 2. BrandPDF Template  (the library)
| Field | Type | Notes |
|---|---|---|
| template_name | Data | primary key (autoname) |
| target_doctype | Link → DocType | |
| language | Select | en / ar / bilingual |
| source_type | Select | **html_body / jinja_file** |
| jinja_path | Data | app-relative path (when source_type = jinja_file) |
| body | Code (HTML/Jinja) | the template (when source_type = html_body); **System-Manager-authored = trusted as developer** |
| is_standard | Check | shipped starters; **read-only — clone to edit** |

Permissions: write = System Manager only. Standard templates ship as fixtures AND are
edit-locked (a `validate` guard blocks edits when `is_standard`), so `migrate` can never
clobber a user's work.

## 3. BrandPDF Mapping  (no-code routing)
| Field | Type | Notes |
|---|---|---|
| target_doctype | Link → DocType | |
| template | Link → BrandPDF Template | |
| enabled | Check | |
| priority | Int | lower wins among overlapping mappings (deterministic precedence) |
| auto_attach | Check | attach PDF on submit |
| replace_print_pdf | Check | route Print>PDF through us |
| replace_email_attach | Check | swap email attachment |
| conditions | Table → BrandPDF Mapping Condition | structured, **no eval** |

### 3a. BrandPDF Mapping Condition (child)
| Field | Type |
|---|---|
| fieldname | Data |
| operator | Select (=, !=, >, <, in, like) |
| value | Data |

Resolution at render time: `doctype → enabled mappings → first whose conditions all match → template`.
Conditions are evaluated with a small structured matcher (fieldname/operator/value) — **never**
`eval`/`safe_eval` (PLAN H8).

---

## Integration toggles (Phase 2/M5)
Only wire Print>PDF / email-attach **after verifying `pdf_generator` is real core v15 API** on
the target build; if it's print_designer-only, integrate via supported
`override_whitelisted_methods` / the custom button, gated per-mapping (PLAN H9). Unmapped
doctypes must behave exactly like stock (least surprise).
