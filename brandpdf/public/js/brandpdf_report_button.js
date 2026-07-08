// Adds a "Branded PDF" button to the Query Report view. It re-runs the report server-side
// (brandpdf.report.report_pdf) with the current filters and streams back a branded PDF — a fully
// styled dynamic table (or a mapped BrandPDF report template when one exists). This is separate
// from the native Print > PDF, which Mode A (report_to_pdf override) wraps automatically.
//
// Attach strategy: the query-report PAGE is a single instance reused for every report, and its
// inner toolbar is CLEARED whenever a report loads/refreshes — so a one-shot add_inner_button
// (with an "already added" flag) loses the button forever. Instead we ENSURE the button exists:
// re-check on route changes and on a slow interval, re-adding whenever the toolbar was wiped.
(function () {
	function currentFilters(qr) {
		try {
			return (qr.get_filter_values && qr.get_filter_values(false)) || {};
		} catch (e) {
			return {}; // required filter missing etc. — send what we can; server re-validates
		}
	}

	function openBrandedPdf(qr) {
		var rn = qr && qr.report_name;
		if (!rn) {
			frappe.msgprint(__('Open a report first.'));
			return;
		}
		var url = '/api/method/brandpdf.report.report_pdf'
			+ '?report_name=' + encodeURIComponent(rn)
			+ '&filters=' + encodeURIComponent(JSON.stringify(currentFilters(qr) || {}));
		window.open(url, '_blank');
	}

	function ensureButton() {
		try {
			if (!frappe.get_route || frappe.get_route()[0] !== 'query-report') return;
			var qr = frappe.query_report;
			if (!qr || !qr.page || !qr.report_name) return;
			var tb = qr.page.inner_toolbar;
			if (tb && tb.find && tb.find('[data-bpdf-btn]').length) return; // still there
			var $btn = qr.page.add_inner_button(__('Branded PDF'), function () {
				openBrandedPdf(frappe.query_report);
			});
			if ($btn && $btn.attr) $btn.attr('data-bpdf-btn', '1');
		} catch (e) { /* never break the report view */ }
	}

	$(document).on('page-change', function () { setTimeout(ensureButton, 600); });
	$(document).ready(function () { setTimeout(ensureButton, 600); });
	setInterval(ensureButton, 1500); // survives toolbar clears on refresh/filter changes
})();
