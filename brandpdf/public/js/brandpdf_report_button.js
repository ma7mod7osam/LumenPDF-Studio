// Adds a "Branded PDF" button to the Query Report view. It re-runs the report server-side
// (brandpdf.report.report_pdf) with the current filters and streams back a branded PDF — a fully
// styled dynamic table (or a mapped BrandPDF report template when one exists). This is separate
// from the native Print > PDF, which Mode A (report_to_pdf override) wraps automatically.
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

	function addButton(tries) {
		if (frappe.get_route && frappe.get_route()[0] !== 'query-report') return;
		var qr = frappe.query_report;
		if (!qr || !qr.page) {
			if ((tries || 0) < 20) setTimeout(function () { addButton((tries || 0) + 1); }, 300);
			return;
		}
		if (qr.__bpdf_report_btn) return; // qr is rebuilt per report, so this de-dupes within a report
		qr.__bpdf_report_btn = true;
		qr.page.add_inner_button(__('Branded PDF'), function () { openBrandedPdf(qr); });
	}

	$(document).on('page-change', function () { addButton(0); });
	$(document).ready(function () { addButton(0); });
})();
