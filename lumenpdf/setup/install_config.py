# Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
# SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
# Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
# trademarks of Lumen Solutions.
"""Phase-2 config spine — programmatic DocType creator.

Per PLAN/PHASE2 docs we do NOT hand-write DocType JSON. The app must be installed & migrated
first (so the LumenPDF Module Def exists). Then, in developer_mode, this creates the DocTypes
AND exports their JSON into the app for version control. Idempotent.

    # app already installed & migrated (Module Def 'LumenPDF' exists)
    bench set-config -g developer_mode 1 && bench restart
    bench --site <site> execute lumenpdf.setup.install_config.run
    bench --site <site> migrate          # re-imports the exported JSON
    # commit the generated lumenpdf/lumenpdf/doctype/* JSON

Can't enable developer_mode? Create Custom DocTypes instead (DB-only, exportable as fixtures):
    bench --site <site> execute lumenpdf.setup.install_config.run --kwargs "{'as_custom': True}"
"""
import frappe

SETTINGS_FIELDS = [
    {"fieldname": "company", "fieldtype": "Link", "label": "Company", "options": "Company", "reqd": 1, "unique": 1, "in_list_view": 1},
    {"fieldname": "branding_sb", "fieldtype": "Section Break", "label": "Branding"},
    {"fieldname": "header_image", "fieldtype": "Attach Image", "label": "Header Image"},
    {"fieldname": "footer_image", "fieldtype": "Attach Image", "label": "Footer Image"},
    {"fieldname": "colors_cb", "fieldtype": "Column Break"},
    {"fieldname": "primary_color", "fieldtype": "Data", "label": "Primary Color (hex)", "default": "#1C75BC", "description": "e.g. #1C75BC"},
    {"fieldname": "secondary_color", "fieldtype": "Data", "label": "Secondary Color (hex)", "default": "#1A1E2A", "description": "e.g. #1A1E2A"},
    {"fieldname": "font_family", "fieldtype": "Select", "label": "Font Family", "options": "Montserrat\nCairo\nArial\nTahoma", "default": "Montserrat"},
    {"fieldname": "page_sb", "fieldtype": "Section Break", "label": "Page"},
    {"fieldname": "page_size", "fieldtype": "Select", "label": "Page Size", "options": "A4\nLetter", "default": "A4"},
    {"fieldname": "brand_reports", "fieldtype": "Check", "label": "Brand report PDFs (wrap Report > PDF in the branded header/footer)"},
    {"fieldname": "rtl", "fieldtype": "Check", "label": "Right-to-Left (Arabic)", "default": "1"},
    {"fieldname": "default_engine", "fieldtype": "Select", "label": "Default Engine", "options": "playwright\ngotenberg", "default": "playwright"},
    {"fieldname": "footer_registration_text", "fieldtype": "Small Text", "label": "Footer Registration Text (CR / VAT)"},
]

TEMPLATE_FIELDS = [
    # autoname makes template_name the primary key, so no separate unique flag (review #12).
    {"fieldname": "template_name", "fieldtype": "Data", "label": "Template Name", "reqd": 1, "in_list_view": 1},
    {"fieldname": "target_kind", "fieldtype": "Select", "label": "Target Kind", "options": "doctype\nreport", "default": "doctype", "in_list_view": 1},
    {"fieldname": "target_doctype", "fieldtype": "Link", "label": "Target DocType", "options": "DocType", "reqd": 1, "in_list_view": 1},
    {"fieldname": "report_name", "fieldtype": "Link", "label": "Report", "options": "Report", "depends_on": "eval:doc.target_kind=='report'"},
    {"fieldname": "language", "fieldtype": "Select", "label": "Language", "options": "en\nar\nbilingual", "default": "bilingual"},
    {"fieldname": "is_standard", "fieldtype": "Check", "label": "Is Standard (read-only)", "read_only": 1},
    {"fieldname": "in_gallery", "fieldtype": "Check", "label": "Show in Templates gallery", "in_list_view": 1},
    {"fieldname": "src_sb", "fieldtype": "Section Break", "label": "Source"},
    {"fieldname": "source_type", "fieldtype": "Select", "label": "Source Type", "options": "blocks\nhtml_body\njinja_file", "default": "blocks"},
    {"fieldname": "blocks", "fieldtype": "Table", "label": "Blocks (compose your format)", "options": "LumenPDF Block", "depends_on": "eval:doc.source_type=='blocks'"},
    {"fieldname": "jinja_path", "fieldtype": "Data", "label": "Jinja File Path (app-relative)", "depends_on": "eval:doc.source_type=='jinja_file'"},
    {"fieldname": "body", "fieldtype": "Code", "label": "Body (HTML/Jinja)", "options": "HTML", "depends_on": "eval:doc.source_type=='html_body'"},
    {"fieldname": "definition", "fieldtype": "Code", "label": "Definition (visual builder JSON)", "options": "JSON", "read_only": 1, "depends_on": "eval:doc.source_type=='blocks'"},
]

BLOCK_FIELDS = [
    {"fieldname": "block_type", "fieldtype": "Select", "label": "Block", "reqd": 1, "in_list_view": 1,
     "options": "header_banner\ntitle\ncustomer\nitems\ntotals\npayment_schedule\nterms\nsignature\nspacer\ncustom_html\nreport_title\nreport_filters\nreport_table\nreport_native\nfooter_banner"},
    {"fieldname": "label", "fieldtype": "Data", "label": "Label / Title (optional)", "in_list_view": 1},
    {"fieldname": "content", "fieldtype": "Code", "label": "Custom HTML (for the custom_html block)", "options": "HTML"},
]

SNIPPET_FIELDS = [
    # Reusable single blocks ("My blocks" in the builder's Insert panel): one configured block —
    # settings + style, rows including their nested children — insertable into any format.
    {"fieldname": "snippet_name", "fieldtype": "Data", "label": "Snippet Name", "reqd": 1, "in_list_view": 1},
    {"fieldname": "block", "fieldtype": "Code", "label": "Block (builder JSON)", "options": "JSON"},
]

CONDITION_FIELDS = [
    {"fieldname": "fieldname", "fieldtype": "Data", "label": "Field Name", "reqd": 1, "in_list_view": 1},
    {"fieldname": "operator", "fieldtype": "Select", "label": "Operator", "options": "=\n!=\n>\n<\n>=\n<=\nin\nlike", "default": "=", "in_list_view": 1},
    {"fieldname": "value", "fieldtype": "Data", "label": "Value", "in_list_view": 1},
]

MAPPING_FIELDS = [
    {"fieldname": "target_kind", "fieldtype": "Select", "label": "Target Kind", "options": "doctype\nreport", "default": "doctype", "in_list_view": 1},
    {"fieldname": "target_doctype", "fieldtype": "Link", "label": "Target DocType", "options": "DocType", "reqd": 1, "in_list_view": 1},
    {"fieldname": "report_name", "fieldtype": "Link", "label": "Report", "options": "Report", "depends_on": "eval:doc.target_kind=='report'"},
    {"fieldname": "template", "fieldtype": "Link", "label": "Template", "options": "LumenPDF Template", "reqd": 1, "in_list_view": 1},
    {"fieldname": "company", "fieldtype": "Link", "label": "Company (blank = all companies)", "options": "Company", "in_list_view": 1},
    {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1},
    {"fieldname": "priority", "fieldtype": "Int", "label": "Priority (lower wins)", "default": "0", "in_list_view": 1},
    {"fieldname": "behavior_sb", "fieldtype": "Section Break", "label": "Behavior"},
    {"fieldname": "auto_attach", "fieldtype": "Check", "label": "Auto-attach PDF on Submit"},
    {"fieldname": "replace_print_pdf", "fieldtype": "Check", "label": "Replace Print > PDF"},
    {"fieldname": "replace_report_pdf", "fieldtype": "Check", "label": "Replace Report > PDF (report targets)"},
    {"fieldname": "replace_email_attach", "fieldtype": "Check", "label": "Replace Email Attachment"},
    {"fieldname": "cond_sb", "fieldtype": "Section Break", "label": "Conditions (all must match)"},
    {"fieldname": "conditions", "fieldtype": "Table", "label": "Conditions", "options": "LumenPDF Mapping Condition"},
]


def run(as_custom=False):
    as_custom = bool(as_custom)
    if not frappe.db.exists("Module Def", "LumenPDF"):
        frappe.throw("Install and migrate the app first — Module Def 'LumenPDF' is missing.")
    if not as_custom and not frappe.conf.get("developer_mode"):
        frappe.throw(
            "Enable developer_mode first (bench set-config -g developer_mode 1; bench restart) so the "
            "DocType JSON exports into the app for version control — or re-run with as_custom=True to "
            "create Custom DocTypes without developer_mode."
        )
    # Order matters: child/referenced DocTypes must exist before the ones that link them.
    # Each step is isolated + committed on success so one failure can't roll back the rest or
    # leave a half-installed state that silently re-fails every migrate (review: medium finding).
    steps = [
        ("LumenPDF Settings", lambda: _ensure("LumenPDF Settings", SETTINGS_FIELDS, as_custom)),
        ("LumenPDF Block", lambda: _ensure("LumenPDF Block", BLOCK_FIELDS, as_custom, istable=1)),
        ("LumenPDF Template", lambda: _ensure("LumenPDF Template", TEMPLATE_FIELDS, as_custom, autoname="field:template_name")),
        ("LumenPDF Snippet", lambda: _ensure("LumenPDF Snippet", SNIPPET_FIELDS, as_custom, autoname="field:snippet_name")),
        ("LumenPDF Mapping Condition", lambda: _ensure("LumenPDF Mapping Condition", CONDITION_FIELDS, as_custom, istable=1)),
        ("LumenPDF Mapping", lambda: _ensure("LumenPDF Mapping", MAPPING_FIELDS, as_custom)),
        ("seed", _seed),
    ]
    failures = []
    for label, fn in steps:
        try:
            fn()
            # Deliberate per-step commit in an install/migrate hook: each DocType step is isolated so
            # one failure (rolled back below) cannot undo the steps that already succeeded.
            frappe.db.commit()  # nosemgrep
        except Exception:
            frappe.db.rollback()
            failures.append(label)
            frappe.log_error(title=f"LumenPDF install step failed: {label}", message=frappe.get_traceback())
    ok = _integrity_check()
    if failures or not ok:
        print("LumenPDF config: completed WITH ISSUES — failed steps:", failures, "(see Error Log)")
    else:
        print(f"LumenPDF config DocTypes ready (custom={as_custom}).")
    return failures


def _integrity_check():
    """Log a clear report if the config didn't fully materialize, so a half-installed state is
    visible instead of silently re-failing each deploy."""
    expected = ["LumenPDF Settings", "LumenPDF Block", "LumenPDF Template", "LumenPDF Mapping Condition", "LumenPDF Mapping"]
    missing = [d for d in expected if not frappe.db.exists("DocType", d)]
    gaps = []
    if frappe.db.exists("DocType", "LumenPDF Template"):
        frappe.clear_cache(doctype="LumenPDF Template")  # avoid stale meta after create/alter
        if "blocks" not in {f.fieldname for f in frappe.get_meta("LumenPDF Template").fields}:
            gaps.append("LumenPDF Template.blocks")
    if missing or gaps:
        frappe.log_error(title="LumenPDF config incomplete", message=f"missing DocTypes={missing}; field gaps={gaps}")
        return False
    return True


def ensure_config():
    """after_migrate hook: create/upgrade the LumenPDF config DocTypes automatically on every
    deploy, as Custom DocTypes (no developer_mode, no manual command). Non-fatal by design —
    a failure here must never abort a site migration."""
    try:
        if not frappe.db.exists("Module Def", "LumenPDF"):
            # On a fresh install this normally exists already (created from modules.txt while the
            # app syncs). Create it rather than bailing, so the config never depends on install
            # ordering — bailing here is what leaves a site with no config DocTypes at all.
            try:
                md = frappe.get_doc({"doctype": "Module Def", "module_name": "LumenPDF",
                                     "app_name": "lumenpdf"})
                md.flags.ignore_permissions = True
                md.insert(ignore_if_duplicate=True)
            except Exception:
                frappe.log_error(title="LumenPDF: could not create Module Def",
                                 message=frappe.get_traceback())
                return
        run(as_custom=True)
    except Exception:
        frappe.log_error(title="LumenPDF: ensure_config failed", message=frappe.get_traceback())


def _deferred_links(fields):
    """Link fields whose target DocType is not installed (e.g. Company without ERPNext).
    They are left out for now; _sync_fields adds them on the first run after the target
    app arrives, so a bare-frappe bench installs clean instead of failing the whole step."""
    return {f["fieldname"] for f in fields
            if f.get("fieldtype") == "Link" and f.get("options")
            and not frappe.db.exists("DocType", f["options"])}


def check_config():
    """Raise if the config spine is incomplete. Used by CI right after install-app and again
    after migrate, so a regression in fresh-install behavior turns the build red instead of
    hiding behind the fail-soft ensure_config."""
    expected = {
        "LumenPDF Settings": SETTINGS_FIELDS,
        "LumenPDF Block": BLOCK_FIELDS,
        "LumenPDF Template": TEMPLATE_FIELDS,
        "LumenPDF Snippet": SNIPPET_FIELDS,
        "LumenPDF Mapping Condition": CONDITION_FIELDS,
        "LumenPDF Mapping": MAPPING_FIELDS,
    }
    problems = []
    for name, fields in expected.items():
        if not frappe.db.exists("DocType", name):
            problems.append(f"missing DocType: {name}")
            continue
        frappe.clear_cache(doctype=name)
        have = {f.fieldname for f in frappe.get_meta(name).fields}
        want = {f["fieldname"] for f in fields} - _deferred_links(fields)
        gaps = sorted(want - have)
        if gaps:
            problems.append(f"{name} is missing fields: {gaps}")
    if problems:
        logs = frappe.get_all("Error Log", filters={"method": ["like", "LumenPDF%"]},
                              fields=["method", "error"], order_by="creation desc", limit=3)
        detail = "\n".join(f"--- {l.method}\n{(l.error or '')[:800]}" for l in logs)
        raise RuntimeError("LumenPDF config incomplete:\n" + "\n".join(problems)
                           + ("\n\nRecent error logs:\n" + detail if logs else ""))
    print("LumenPDF config check: complete.")


def _ensure(name, fields, as_custom, istable=0, autoname=None):
    if frappe.db.exists("DocType", name):
        _sync_fields(name, fields)
        return
    deferred = _deferred_links(fields)
    if deferred:
        print("  deferring link fields on", name, "until their DocTypes exist:", sorted(deferred))
        fields = [f for f in fields if f["fieldname"] not in deferred]
    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": name,
            "module": "LumenPDF",
            "custom": 1 if as_custom else 0,
            "istable": istable,
            "editable_grid": 1 if istable else 0,
            "engine": "InnoDB",
            "autoname": autoname,
            "fields": fields,
            "permissions": [] if istable else _perms(),
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert()
    print("  created:", name)


def _sync_fields(name, fields):
    """Add any fields missing from an already-created DocType (handles app upgrades, e.g. the
    new Blocks table). Uses Custom Fields so it works on standard or custom DocTypes without
    developer_mode."""
    existing = {f.fieldname for f in frappe.get_meta(name).fields}
    deferred = _deferred_links(fields)
    missing = [f for f in fields if f["fieldname"] not in existing and f["fieldname"] not in deferred]
    if not missing:
        return
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({name: missing}, ignore_validate=True)
    print("  added fields on", name, ":", [f["fieldname"] for f in missing])


def _perms():
    return [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
             "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}]


def _seed():
    """Starter content for FRESH installs: one editable block-based Quotation format + a mapping,
    so 'Download Branded PDF' works out of the box. Nothing client-branded; guarded so a plain
    Frappe site (no ERPNext / no Quotation doctype) skips it. Existing sites are untouched — every
    insert is exists-guarded, and the mapping guard never overrides a site's chosen default."""
    if not frappe.db.exists("DocType", "Quotation"):
        return
    bname = "Quotation - Starter"
    if not frappe.db.exists("LumenPDF Template", bname):
        from lumenpdf.blocks import default_blocks
        bt = frappe.get_doc(
            {
                "doctype": "LumenPDF Template",
                "template_name": bname,
                "target_doctype": "Quotation",
                "language": "en",
                "is_standard": 0,
                "source_type": "blocks",
                "blocks": [{"block_type": blk["block_type"]} for blk in default_blocks()],
            }
        )
        bt.flags.ignore_permissions = True
        bt.insert()
        print("  seeded starter template:", bname)
    if not frappe.db.exists("LumenPDF Mapping", {"target_doctype": "Quotation"}):
        m = frappe.get_doc(
            {"doctype": "LumenPDF Mapping", "target_doctype": "Quotation", "template": bname, "enabled": 1, "priority": 0}
        )
        m.flags.ignore_permissions = True
        m.insert()
        print("  seeded mapping: Quotation ->", bname)
