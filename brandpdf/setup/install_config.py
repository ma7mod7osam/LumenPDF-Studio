"""Phase-2 config spine — programmatic DocType creator.

Per PLAN/PHASE2 docs we do NOT hand-write DocType JSON. Run this ONCE on the bench; in
developer_mode it creates the DocTypes AND exports their JSON into the app for version
control (then commit them). Idempotent.

    bench set-config -g developer_mode 1 && bench restart
    bench --site <site> execute brandpdf.setup.install_config.run
    bench --site <site> migrate
    # commit the generated brandpdf/brandpdf/doctype/* JSON

Can't enable developer_mode? Create Custom DocTypes instead (DB-only, exportable as fixtures):
    bench --site <site> execute brandpdf.setup.install_config.run --kwargs "{'as_custom': True}"
"""
import frappe

SETTINGS_FIELDS = [
    {"fieldname": "company", "fieldtype": "Link", "label": "Company", "options": "Company", "reqd": 1, "unique": 1, "in_list_view": 1},
    {"fieldname": "branding_sb", "fieldtype": "Section Break", "label": "Branding"},
    {"fieldname": "header_image", "fieldtype": "Attach Image", "label": "Header Image"},
    {"fieldname": "footer_image", "fieldtype": "Attach Image", "label": "Footer Image"},
    {"fieldname": "colors_cb", "fieldtype": "Column Break"},
    {"fieldname": "primary_color", "fieldtype": "Data", "label": "Primary Color", "default": "#1C75BC"},
    {"fieldname": "secondary_color", "fieldtype": "Data", "label": "Secondary Color", "default": "#1A1E2A"},
    {"fieldname": "font_family", "fieldtype": "Data", "label": "Font Family", "default": "Montserrat"},
    {"fieldname": "page_sb", "fieldtype": "Section Break", "label": "Page"},
    {"fieldname": "page_size", "fieldtype": "Select", "label": "Page Size", "options": "A4\nLetter", "default": "A4"},
    {"fieldname": "rtl", "fieldtype": "Check", "label": "Right-to-Left (Arabic)", "default": "1"},
    {"fieldname": "default_engine", "fieldtype": "Select", "label": "Default Engine", "options": "playwright\ngotenberg", "default": "playwright"},
    {"fieldname": "footer_registration_text", "fieldtype": "Small Text", "label": "Footer Registration Text (CR / VAT)"},
]

TEMPLATE_FIELDS = [
    {"fieldname": "template_name", "fieldtype": "Data", "label": "Template Name", "reqd": 1, "unique": 1, "in_list_view": 1},
    {"fieldname": "target_doctype", "fieldtype": "Link", "label": "Target DocType", "options": "DocType", "reqd": 1, "in_list_view": 1},
    {"fieldname": "language", "fieldtype": "Select", "label": "Language", "options": "en\nar\nbilingual", "default": "bilingual"},
    {"fieldname": "is_standard", "fieldtype": "Check", "label": "Is Standard (read-only)", "read_only": 1},
    {"fieldname": "src_sb", "fieldtype": "Section Break", "label": "Source"},
    {"fieldname": "source_type", "fieldtype": "Select", "label": "Source Type", "options": "html_body\njinja_file", "default": "html_body"},
    {"fieldname": "jinja_path", "fieldtype": "Data", "label": "Jinja File Path (app-relative)", "depends_on": "eval:doc.source_type=='jinja_file'"},
    {"fieldname": "body", "fieldtype": "Code", "label": "Body (HTML/Jinja)", "options": "HTML", "depends_on": "eval:doc.source_type=='html_body'"},
]

CONDITION_FIELDS = [
    {"fieldname": "fieldname", "fieldtype": "Data", "label": "Field Name", "reqd": 1, "in_list_view": 1},
    {"fieldname": "operator", "fieldtype": "Select", "label": "Operator", "options": "=\n!=\n>\n<\n>=\n<=\nin\nlike", "default": "=", "in_list_view": 1},
    {"fieldname": "value", "fieldtype": "Data", "label": "Value", "in_list_view": 1},
]

MAPPING_FIELDS = [
    {"fieldname": "target_doctype", "fieldtype": "Link", "label": "Target DocType", "options": "DocType", "reqd": 1, "in_list_view": 1},
    {"fieldname": "template", "fieldtype": "Link", "label": "Template", "options": "BrandPDF Template", "reqd": 1, "in_list_view": 1},
    {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1},
    {"fieldname": "behavior_sb", "fieldtype": "Section Break", "label": "Behavior"},
    {"fieldname": "auto_attach", "fieldtype": "Check", "label": "Auto-attach PDF on Submit"},
    {"fieldname": "replace_print_pdf", "fieldtype": "Check", "label": "Replace Print > PDF"},
    {"fieldname": "replace_email_attach", "fieldtype": "Check", "label": "Replace Email Attachment"},
    {"fieldname": "cond_sb", "fieldtype": "Section Break", "label": "Conditions (all must match)"},
    {"fieldname": "conditions", "fieldtype": "Table", "label": "Conditions", "options": "BrandPDF Mapping Condition"},
]


def run(as_custom=False):
    as_custom = bool(as_custom)
    if not as_custom and not frappe.conf.get("developer_mode"):
        frappe.throw(
            "Enable developer_mode first (bench set-config -g developer_mode 1; bench restart) so the "
            "DocType JSON exports into the app for version control — or re-run with as_custom=True to "
            "create Custom DocTypes without developer_mode."
        )
    # Order matters: referenced DocTypes (Template, Condition) must exist before Mapping.
    _ensure("BrandPDF Settings", SETTINGS_FIELDS, as_custom)
    _ensure("BrandPDF Template", TEMPLATE_FIELDS, as_custom, autoname="field:template_name")
    _ensure("BrandPDF Mapping Condition", CONDITION_FIELDS, as_custom, istable=1)
    _ensure("BrandPDF Mapping", MAPPING_FIELDS, as_custom)
    _seed()
    frappe.db.commit()
    print(f"BrandPDF config DocTypes ready (custom={as_custom}).")


def _ensure(name, fields, as_custom, istable=0, autoname=None):
    if frappe.db.exists("DocType", name):
        print("  exists:", name)
        return
    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": name,
            "module": "BrandPDF",
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


def _perms():
    return [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
             "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}]


def _seed():
    """Wire the BSTC Quotation out of the box: a standard (read-only) template + a mapping."""
    tname = "Quotation - BSTC"
    if not frappe.db.exists("BrandPDF Template", tname):
        t = frappe.get_doc(
            {
                "doctype": "BrandPDF Template",
                "template_name": tname,
                "target_doctype": "Quotation",
                "language": "bilingual",
                "is_standard": 1,
                "source_type": "jinja_file",
                "jinja_path": "templates/brandpdf/quotation_bstc.html",
            }
        )
        t.flags.brandpdf_allow_standard_edit = True
        t.flags.ignore_permissions = True
        t.insert()
        print("  seeded template:", tname)
    if not frappe.db.exists("BrandPDF Mapping", {"target_doctype": "Quotation"}):
        m = frappe.get_doc(
            {"doctype": "BrandPDF Mapping", "target_doctype": "Quotation", "template": tname, "enabled": 1}
        )
        m.flags.ignore_permissions = True
        m.insert()
        print("  seeded mapping: Quotation ->", tname)
