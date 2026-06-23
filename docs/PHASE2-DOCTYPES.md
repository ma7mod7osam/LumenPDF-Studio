# Phase 2 — Config DocTypes (the no-code spine)

> Build these **on the live bench** with `bench --site <site> make-doctype` (or the Desk
> DocType UI) so the JSON is generated correctly. Do NOT hand-write the JSON — that's how
> you ship broken metadata. This file is the spec to build from, only after M0–M3 prove the
> BSTC Quotation loop (PLAN §5).

When these exist, update `render_html.get_branding()` to read `BrandPDF Settings` by
`doc.company`, and add a resolver that picks the template via `BrandPDF Mapping`. The public
function signatures don't change.

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
| template_name | Data | unique |
| target_doctype | Link → DocType | |
| language | Select | en / ar / bilingual |
| source_type | Select | jinja / print_format |
| body | Code (HTML/Jinja) | the template |
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
