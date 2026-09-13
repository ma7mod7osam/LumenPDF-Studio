// Global desk script: registers a "Download Branded PDF" button on every DocType that has
// an enabled LumenPDF Mapping (falls back to Quotation). POSTs to the queued endpoint and
// polls for the private file URL (PLAN H6/H7). No GET/window.open of the endpoint itself.

frappe.provide("lumenpdf");

(function () {
    if (lumenpdf._wired) return;
    lumenpdf._wired = true;

    frappe.call({
        method: "lumenpdf.api.enabled_doctypes",
        callback(r) {
            const dts = r.message || ["Quotation"];
            dts.forEach(function (dt) {
                frappe.ui.form.on(dt, { refresh: lumenpdf_add_button });
            });
            // The current form's refresh already fired before this async call returned, so
            // add the button to it now (the dominant "open form by URL" path) — review #4.
            const open_frm = frappe.container && frappe.container.page && frappe.container.page.frm;
            if (open_frm && open_frm.doctype && dts.indexOf(open_frm.doctype) > -1) {
                lumenpdf_add_button(open_frm);
            }
        },
    });
})();

function lumenpdf_add_button(frm) {
    if (frm.is_new()) return;
    // Dedup: refresh fires on every reload/save/workflow action — review #6.
    if (frm.custom_buttons && frm.custom_buttons[__("Download Branded PDF")]) return;
    frm.add_custom_button(__("Download Branded PDF"), () => lumenpdf_generate(frm));
}

function lumenpdf_generate(frm) {
    // If the doctype has more than one format, let the user choose; otherwise render directly.
    frappe.call({
        method: "lumenpdf.api.list_formats",
        args: { doctype: frm.doc.doctype, company: frm.doc.company || "" },  // company default marked ★
        callback(r) {
            const formats = r.message || [];
            if (formats.length > 1) {
                // Option value = template name (labels can repeat / carry the ★ default marker).
                const def = formats.find((f) => f.is_default) || formats[0];
                const d = new frappe.ui.Dialog({
                    title: __("Choose a format"),
                    fields: [{
                        fieldname: "fmt", fieldtype: "Select", label: __("Format"), reqd: 1,
                        options: formats.map((f) => ({
                            value: f.name, label: f.label + (f.is_default ? "  ★ " + __("default") : ""),
                        })),
                        default: def.name,
                    }],
                    primary_action_label: __("Download"),
                    primary_action(v) {
                        d.hide();
                        lumenpdf_run(frm, v.fmt || def.name);
                    },
                });
                d.show();
            } else {
                lumenpdf_run(frm, formats[0] ? formats[0].name : null);
            }
        },
        error() {
            lumenpdf_run(frm, null);  // fall back to the default format
        },
    });
}

function lumenpdf_run(frm, template) {
    frappe.dom.freeze(__("Generating branded PDF…"));
    frappe.call({
        method: "lumenpdf.api.request_pdf",
        args: { doctype: frm.doc.doctype, name: frm.doc.name, template: template || "" },
        callback(r) {
            const job_id = r.message && r.message.job_id;
            if (!job_id) {
                frappe.dom.unfreeze();
                frappe.msgprint(__("Could not start the PDF job."));
                return;
            }
            lumenpdf_poll(job_id, 0);
        },
        error() {
            frappe.dom.unfreeze();
        },
    });
}

function lumenpdf_poll(job_id, tries) {
    if (tries > 80) {
        frappe.dom.unfreeze();
        frappe.msgprint(__("PDF generation timed out. Please try again."));
        return;
    }
    frappe.call({
        method: "lumenpdf.api.get_job_result",
        args: { job_id },
        callback(r) {
            const s = r.message || {};
            if (s.status === "done" && s.file_url) {
                frappe.dom.unfreeze();
                window.open(s.file_url, "_blank");
            } else if (s.status === "error") {
                frappe.dom.unfreeze();
                frappe.msgprint(__(s.message || "Render failed."));
            } else {
                setTimeout(() => lumenpdf_poll(job_id, tries + 1), 1500);
            }
        },
        error() {
            frappe.dom.unfreeze();
        },
    });
}
