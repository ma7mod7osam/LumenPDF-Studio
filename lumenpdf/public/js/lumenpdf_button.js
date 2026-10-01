// Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
// SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
// Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
// trademarks of Lumen Solutions.
// Global desk script: registers a branded "Print with LumenPDF" button on every DocType that
// has an enabled LumenPDF Mapping (falls back to Quotation). The button routes to our own print
// screen, which renders, previews, prints, downloads and emails the document.

frappe.provide("lumenpdf");
frappe.provide("frappe.listview_settings");

(function () {
    if (lumenpdf._wired) return;
    lumenpdf._wired = true;

    frappe.call({
        method: "lumenpdf.api.enabled_doctypes",
        callback(r) {
            const dts = r.message || ["Quotation"];
            dts.forEach(function (dt) {
                frappe.ui.form.on(dt, { refresh: lumenpdf_add_button });
                lumenpdf_wire_list(dt);
            });
            // The list may already be on screen when this async call returns.
            const lv = frappe.get_route()[0] === "List" && cur_list;
            if (lv && dts.indexOf(lv.doctype) > -1) lumenpdf_add_list_action(lv);
            // The current form's refresh already fired before this async call returned, so
            // add the button to it now (the dominant "open form by URL" path) — review #4.
            const open_frm = frappe.container && frappe.container.page && frappe.container.page.frm;
            if (open_frm && open_frm.doctype && dts.indexOf(open_frm.doctype) > -1) {
                lumenpdf_add_button(open_frm);
            }
        },
    });
})();

// Our own mark on the button: the person printing should know whose screen they are about to
// land on, and find their way back to it next time.
const BRANDPDF_MARK =
    '<svg viewBox="0 0 48 48" width="14" height="14" style="margin-right:6px;vertical-align:-2px;flex:0 0 auto" aria-hidden="true">'
    + '<rect width="48" height="48" rx="11" fill="#1463FF"></rect>'
    + '<rect x="15" y="11" width="18" height="26" rx="3" fill="none" stroke="#fff" stroke-width="2.6"></rect>'
    + '<path d="M20 19h8M20 24h8M20 29h5" stroke="#fff" stroke-width="2.6" stroke-linecap="round"></path>'
    + '</svg>';

function lumenpdf_add_button(frm) {
    if (frm.is_new()) return;
    const label = __("Print with LumenPDF");
    // Dedup: refresh fires on every reload/save/workflow action — review #6.
    if (frm.custom_buttons && frm.custom_buttons[label]) return;
    const $btn = frm.add_custom_button(label, () => lumenpdf_open_print(frm));
    // add_custom_button renders plain text; dress it with the mark without losing the handler.
    try {
        $btn.html(BRANDPDF_MARK + '<span>' + frappe.utils.escape_html(label) + '</span>');
        $btn.css({ display: 'inline-flex', "align-items": 'center' });
    } catch (e) {
        // a future Frappe may return something else; the plain button still works
    }
}

// The list view gets the same door: tick the rows, pick a format once, get one PDF.
function lumenpdf_wire_list(dt) {
    const ls = (frappe.listview_settings[dt] = frappe.listview_settings[dt] || {});
    if (ls._lumenpdf) return;
    ls._lumenpdf = true;
    const prev = ls.onload;
    ls.onload = function (listview) {
        if (prev) prev(listview);
        lumenpdf_add_list_action(listview);
    };
}

function lumenpdf_add_list_action(listview) {
    if (!listview || !listview.page || listview._lumenpdf_item) return;
    listview._lumenpdf_item = true;
    listview.page.add_actions_menu_item(__("Print with LumenPDF"), function () {
        const rows = listview.get_checked_items(true) || [];
        if (!rows.length) {
            frappe.msgprint(__("Tick the documents you want to print."));
            return;
        }
        lumenpdf_bulk_dialog(listview.doctype, rows);
    }, false);
}

function lumenpdf_bulk_dialog(doctype, names) {
    frappe.call({
        method: "lumenpdf.api.list_formats",
        args: { doctype: doctype },
        callback(r) {
            const formats = r.message || [];
            if (!formats.length) {
                frappe.msgprint(__("No LumenPDF format is set up for this document type yet."));
                return;
            }
            const def = formats.find((f) => f.is_default) || formats[0];
            const d = new frappe.ui.Dialog({
                title: __("Print {0} documents", [names.length]),
                fields: [
                    {
                        fieldname: "fmt", fieldtype: "Select", label: __("Format"), reqd: 1,
                        options: formats.map((f) => ({
                            value: f.name,
                            label: f.label + (f.is_default ? "  \u2605 " + __("default") : ""),
                        })),
                        default: def.name,
                    },
                    {
                        fieldtype: "HTML", fieldname: "note",
                        options: `<div class="text-muted small">${__("They come back as one PDF, in the order they are listed.")}</div>`,
                    },
                ],
                primary_action_label: __("Print"),
                primary_action(v) {
                    d.hide();
                    lumenpdf_bulk_run(doctype, names, v.fmt || def.name);
                },
            });
            d.show();
        },
    });
}

function lumenpdf_bulk_run(doctype, names, template) {
    frappe.dom.freeze(__("Printing {0} documents...", [names.length]));
    frappe.call({
        method: "lumenpdf.api.request_bulk_pdf",
        args: { doctype: doctype, names: names, template: template || "" },
        callback(r) {
            const job = (r.message || {}).job_id;
            if (!job) {
                frappe.dom.unfreeze();
                frappe.msgprint(__("Could not start the print."));
                return;
            }
            lumenpdf_bulk_poll(job, 0, names.length);
        },
        error() { frappe.dom.unfreeze(); },
    });
}

function lumenpdf_bulk_poll(job, tries, total) {
    if (tries > 600) {
        frappe.dom.unfreeze();
        frappe.msgprint(__("The print timed out."));
        return;
    }
    frappe.call({
        method: "lumenpdf.api.get_job_result",
        args: { job_id: job },
        callback(r) {
            const s = r.message || {};
            if (s.status === "done" && s.file_url) {
                frappe.dom.unfreeze();
                window.open(s.file_url, "_blank");
                if (s.skipped && s.skipped.length) {
                    frappe.msgprint({
                        title: __("Some documents were left out"),
                        message: __("Printed {0}. These could not be printed: {1}",
                            [s.printed, frappe.utils.escape_html(s.skipped.join(", "))]),
                        indicator: "orange",
                    });
                }
            } else if (s.status === "error") {
                frappe.dom.unfreeze();
                frappe.msgprint(__(s.message || "The print failed."));
            } else {
                if (s.done) frappe.dom.freeze(__("Printing {0} of {1}...", [s.done, s.total || total]));
                setTimeout(() => lumenpdf_bulk_poll(job, tries + 1, total), 1200);
            }
        },
        error() { frappe.dom.unfreeze(); },
    });
}

// The button's whole job: hand the document to our own print screen, where the person can
// switch formats, see the real file, then print, download or email it. ERPNext's print view
// is still one click away from there: we add a way in, we never take one away.
function lumenpdf_open_print(frm) {
    frappe.set_route("lumenpdf-print", frm.doc.doctype, frm.doc.name);
}
