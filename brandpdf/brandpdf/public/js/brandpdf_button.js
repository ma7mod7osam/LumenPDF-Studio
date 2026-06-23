// Adds a "Download Branded PDF" button to the form, POSTs to the queued endpoint,
// and polls for the private file URL (PLAN H6/H7). No GET/window.open of the endpoint.

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Download Branded PDF"), () => brandpdf_generate(frm));
    },
});

function brandpdf_generate(frm) {
    frappe.dom.freeze(__("Generating branded PDF…"));
    frappe.call({
        method: "brandpdf.api.request_pdf",
        args: { doctype: frm.doc.doctype, name: frm.doc.name },
        callback(r) {
            const job_id = r.message && r.message.job_id;
            if (!job_id) {
                frappe.dom.unfreeze();
                frappe.msgprint(__("Could not start the PDF job."));
                return;
            }
            brandpdf_poll(job_id, 0);
        },
        error() {
            frappe.dom.unfreeze();
        },
    });
}

function brandpdf_poll(job_id, tries) {
    if (tries > 80) {
        frappe.dom.unfreeze();
        frappe.msgprint(__("PDF generation timed out. Please try again."));
        return;
    }
    frappe.call({
        method: "brandpdf.api.get_job_result",
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
                setTimeout(() => brandpdf_poll(job_id, tries + 1), 1500);
            }
        },
        error() {
            frappe.dom.unfreeze();
        },
    });
}
