Verified everything. Key findings confirmed:
- Button JS: registers handlers inside async callback (integration #1 real), no dedup guard (integration #2 real).
- `cleanup_expired_files()` exists with no `doc` param — fine, scheduler-safe (integration #6 = non-issue).
- `protect_standard_template` has NO migrate bypass (resolver-sec HIGH confirmed; integration #7's "migrate can't clobber" is wrong — migrate would hard-fail on a standard-template update).
- `render_html` calls `frappe.render_template` on raw DB `body` string (resolver-sec BLOCKER confirmed).

Here is the consolidated list.

---

# LumenPDF Phase-2 Config Spine — Consolidated Fix List

## [BLOCKER]

**1. Arbitrary template execution via `LumenPDF Template.body`**
File: `lumenpdf/render_html.py:34` (+ `resolver.py:62`)
Problem: `frappe.render_template(src, ...)` runs raw user-authored DB `body` HTML through Jinja with `frappe.get_doc`/`frappe.db.sql` injected into globals — strictly more powerful than the eval-free condition matcher, contradicting the spec's "never eval / no-code-safe" claim.
Fix: Keep `body` authoring behind the existing System-Manager-only perm and treat body authors as trusted developers; remove the non-eval-safety claim from the spec for the `body` path. If non-developers must author bodies, route through a restricted/sandboxed context (`frappe.utils.jinja`) instead of the default jenv. At minimum, document body authors == developers.

## [HIGH]

**2. `protect_standard_template` hard-fails `bench migrate`**
File: `lumenpdf/resolver.py:73`
Problem: Guard fires on any update of an `is_standard` row when `not is_new()`. A fixture/migrate re-sync that updates the standard template sets no `lumenpdf_allow_standard_edit` flag, so it `frappe.throw`s and aborts the migration — the opposite of the spec's "migrate can never clobber user work." (Confirmed: source has no migrate bypass; the seed flag is dead code on insert since insert is already skipped by `is_new()`.)
Fix:
```python
if doc.get("is_standard") and not doc.is_new():
    if frappe.flags.in_migrate or frappe.flags.in_install:
        return
    if not getattr(doc.flags, "lumenpdf_allow_standard_edit", False):
        frappe.throw("Standard LumenPDF templates are read-only. Duplicate to edit.")
```
Also remove the now-redundant flag from `install_config.py:124` `_seed`.

**3. Missing `Module Def` guard can hard-fail DocType `insert()`**
File: `lumenpdf/setup/install_config.py:89` (top of `run()`)
Problem: `"module": "LumenPDF"` requires a `Module Def` row, not just the `modules.txt` line. If the seeder runs before install/migrate syncs `modules.txt` → Module Def, `insert()` fails with "Module LumenPDF not found."
Fix: At top of `run()`:
```python
if not frappe.db.exists("Module Def", "LumenPDF"):
    frappe.throw("Install/migrate the app first (Module Def 'LumenPDF' missing).")
```

**4. Branded button never appears on the already-open form (dominant entry path)**
File: `lumenpdf/public/js/lumenpdf_button.js`
Problem: `frappe.ui.form.on(dt, {refresh})` is registered inside the async `enabled_doctypes()` callback. On a direct form URL load, `refresh` has already fired, so the button is absent until the user navigates away and back.
Fix: After the `forEach`, re-apply to the current form:
```js
if (window.cur_frm && (r.message || ["Quotation"]).indexOf(cur_frm.doctype) > -1 && !cur_frm.is_new()) {
    cur_frm.add_custom_button(__("Download Branded PDF"), () => lumenpdf_generate(cur_frm));
}
```
(Combine with fix #6's dedup guard.)

**5. Numeric/`like` condition matching silently mis-matches or matches everything**
File: `lumenpdf/resolver.py:90-105` (`_match`)
Problem: (a) `=`/`!=` are string-only, so float/Currency/Datetime fields stringify mismatched (`5.0` != `"5"`); (b) `like` with empty/`"%"` value matches everything, silently turning a misconfigured row into a no-op; (c) `>`/`<` on date fields always return `False` (not float-parseable), silently dropping the condition.
Fix: For `=`/`!=`, normalize numerics first (`try: return float(a)==float(e)` before string compare). Reject/validate empty `value` for `like` at the Condition level. Document that `> < >= <=` are numeric-only.

## [MEDIUM]

**6. Duplicate "Download Branded PDF" buttons on every refresh**
File: `lumenpdf/public/js/lumenpdf_button.js`
Problem: `refresh` fires on every reload/save/workflow action; `add_custom_button` re-adds with no dedup.
Fix:
```js
refresh(frm) {
    if (frm.is_new()) return;
    if (frm.custom_buttons && frm.custom_buttons[__("Download Branded PDF")]) return;
    frm.add_custom_button(__("Download Branded PDF"), () => lumenpdf_generate(frm));
}
```

**7. `enabled_doctypes()` returns unfiltered list to any logged-in user**
File: `lumenpdf/api.py:40` (+ resolver `enabled_doctypes`)
Problem: Low-sensitivity info leak (which doctypes are branded); more importantly drives the button onto doctypes the user can't read, so the button appears then `_authorize` throws PermissionError on click — confusing UX.
Fix: Filter by read perm: `return [dt for dt in resolver.enabled_doctypes() if frappe.has_permission(dt, "read")]`. Fixes both the leak and the dead-button UX.

**8. `frappe.log_error` logs empty body — loses the traceback it's meant to capture**
File: `lumenpdf/resolver.py:42` (and the template path ~line 64)
Problem: Blanket `except Exception:` calls `frappe.log_error(title=...)` with no `message`, so the traceback is lost; a bad Settings value (e.g. non-hex color) silently flows into rendered CSS, undebuggable.
Fix: `frappe.log_error(title="LumenPDF branding resolve failed", message=frappe.get_traceback())` in both handlers. Add the `^#[0-9A-Fa-f]{6}$` hex validation the spec mentions to the Settings DocType (currently never added in `install_config.py`).

**9. Resolver ↔ render_html import asymmetry is a latent cycle foot-gun**
File: `lumenpdf/resolver.py:11` / `lumenpdf/render_html.py:29`
Problem: No cycle today (render_html's `from lumenpdf import resolver` is lazy/in-function), but it's brittle: a natural refactor adding a top-level `from lumenpdf import resolver` to render_html yields a partial-init `ImportError` (`DEFAULT_BRANDING` undefined mid-init).
Fix: Move `DEFAULT_BRANDING`/`TEMPLATE_MAP` into a leaf module `lumenpdf/defaults.py` that both import; neither depends on the other.

**10. Mapping precedence is non-deterministic (`order_by="modified desc"`)**
File: `lumenpdf/resolver.py:55`
Problem: "First matching enabled mapping wins" ordered by `modified desc`, so re-saving any unrelated mapping silently reorders precedence among overlapping conditional mappings.
Fix: Add an explicit `priority` Int field to LumenPDF Mapping; `order_by="priority asc, creation asc"`.

**11. Document drift (3 stale spec entries — code is correct, docs are wrong)**
File: `PHASE2-DOCTYPES.md`
Problem: (a) line 47 says `source_type` options are `jinja / print_format`; code is `html_body / jinja_file` (resolver checks `"jinja_file"`). (b) line 32 says `font_family` is a `Select` of bundled fonts; code is `Data` (lets users type an unbundled font → silent render break). (c) general option-list mismatches.
Fix: Update doc to `html_body / jinja_file`. Decide intent on `font_family`: either make it `Select` with the bundled-font `options` list (recommended, prevents broken renders) or accept `Data` and fix the doc.

## [LOW]

**12. Redundant `unique:1` on `template_name` alongside `autoname="field:template_name"`**
File: `lumenpdf/setup/install_config.py:34` / `:73`
Problem: Autoname already makes `template_name` the primary key; the extra `unique:1` is a redundant double-constraint with rename friction.
Fix: Drop `unique:1` from the `template_name` field def.

**13. Install/migrate ordering hazard for fresh checkouts with committed JSON**
File: `lumenpdf/setup/install_config.py` docstring
Problem: In developer_mode, `run()` both inserts into DB and exports JSON to disk; `migrate` re-imports that JSON. On a fresh site where the JSON is already committed but the DB row was wiped, the docstring's `run → migrate` order risks a duplicate-path conflict (migrate creates the DocType the seeder also creates).
Fix: Document the strict order **install → migrate → run → migrate → commit**, or have the existence check also bail when the on-disk JSON exists. The current docstring order is the inverse of safe.

---

### Dropped as non-issues (verified fine, do not fix)
- Child DocType (`istable=1`) with empty `permissions` — correct; child tables inherit parent perms.
- Explicit `fieldname`s on Section/Column Breaks — correct, aids idempotent re-export.
- `engine: "InnoDB"` on all four — valid.
- `db.exists` dict-filter existence check (`{"target_doctype": "Quotation"}`) — supported in v15.
- Creation order (Template + Condition before Mapping) — correct.
- `app_include_js` asset path — resolves correctly; bundling doesn't affect plain-file passthrough.
- `cleanup_expired_files` scheduler target — confirmed exists in `pdf_job.py:91` with a no-arg signature; scheduler-safe.
- Dangling `doc_events["LumenPDF Template"]` before DocType creation — inert until a doc is saved.
- `_read_template` realpath confinement, user-scoped job result, enqueued (not inline) render, allowlisted image inlining, no client-supplied template path — all hold.
- `_authorize` re-checks `check_permission("read")` after `enabled_doctypes` — no privilege bypass.

---

## TOP FIXES BEFORE RUNNING THE CREATOR ON A BENCH
1. **#3 Module Def guard** (`install_config.py run()`) — without it `insert()` can hard-fail on a not-yet-migrated site; this is the one true pre-condition for the creator itself.
2. **#2 migrate-safe standard-template guard** (`resolver.py:73`) — the seeded standard template will brick the very next `bench migrate` on update; fix before any second migrate.
3. **#1 body-template RCE / non-eval claim** (`render_html.py:34`) — gate body authoring to System Manager and correct the safety claim before the config spine is documented as "no-code-safe."
4. **#4 + #6 button on open form + dedup** (`lumenpdf_button.js`) — without these the feature is invisible on the dominant entry path and double-renders buttons; cheap combined fix in the one `refresh` handler.