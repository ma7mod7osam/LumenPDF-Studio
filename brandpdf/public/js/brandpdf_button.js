// Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
// SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
// Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
// trademarks of Lumen Solutions.
// Global desk script: registers a branded "Print with LumenPDF" button on every DocType that
// has an enabled BrandPDF Mapping (falls back to Quotation). The button routes to our own print
// screen, which renders, previews, prints, downloads and emails the document.

frappe.provide("brandpdf");

(function () {
    if (brandpdf._wired) return;
    brandpdf._wired = true;

    frappe.call({
        method: "brandpdf.api.enabled_doctypes",
        callback(r) {
            const dts = r.message || ["Quotation"];
            dts.forEach(function (dt) {
                frappe.ui.form.on(dt, { refresh: brandpdf_add_button });
            });
            // The current form's refresh already fired before this async call returned, so
            // add the button to it now (the dominant "open form by URL" path) — review #4.
            const open_frm = frappe.container && frappe.container.page && frappe.container.page.frm;
            if (open_frm && open_frm.doctype && dts.indexOf(open_frm.doctype) > -1) {
                brandpdf_add_button(open_frm);
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

function brandpdf_add_button(frm) {
    if (frm.is_new()) return;
    const label = __("Print with LumenPDF");
    // Dedup: refresh fires on every reload/save/workflow action — review #6.
    if (frm.custom_buttons && frm.custom_buttons[label]) return;
    const $btn = frm.add_custom_button(label, () => brandpdf_open_print(frm));
    // add_custom_button renders plain text; dress it with the mark without losing the handler.
    try {
        $btn.html(BRANDPDF_MARK + '<span>' + frappe.utils.escape_html(label) + '</span>');
        $btn.css({ display: 'inline-flex', "align-items": 'center' });
    } catch (e) {
        // a future Frappe may return something else; the plain button still works
    }
}

// The button's whole job: hand the document to our own print screen, where the person can
// switch formats, see the real file, then print, download or email it. ERPNext's print view
// is still one click away from there: we add a way in, we never take one away.
function brandpdf_open_print(frm) {
    frappe.set_route("brandpdf-print", frm.doc.doctype, frm.doc.name);
}
