// Copyright (c) 2026 Lumen Solutions (BSTC W.L.L)
// SPDX-License-Identifier: AGPL-3.0-only
// "LumenPDF" and "LumenPDF Studio" are trademarks of Lumen Solutions. See TRADEMARKS.md.
// Adds a "Branded PDF" button to the Query Report view. It re-runs the report server-side
// (lumenpdf.report.report_pdf) with the current filters and streams back a branded PDF — a fully
// styled dynamic table (or a mapped LumenPDF report template when one exists). This is separate
// from the native Print > PDF, which Mode A (report_to_pdf override) wraps automatically.
//
// Attach strategy (3rd iteration — the first two lost):
//   * page.add_inner_button puts the button in .custom-actions, which the report view clears AND
//     sometimes hides; frappe's add_inner_button dedupes by label and returns the existing hidden
//     button WITHOUT unhiding — so any API-based re-add can deadlock into "exists but invisible".
//   * So we bypass the API: a plain DOM button PREPENDED into .standard-actions — the container
//     that holds the refresh icon and ⋯ menu, which the report view never clears or hides.
//   * An ensure loop (route change + slow interval) re-adds it if anything removes it.
// This file is a .bundle.js so every deploy ships under a fresh hashed URL (no stale-cache doubt).
(function () {
	function currentFilters(qr) {
		try {
			return (qr.get_filter_values && qr.get_filter_values(false)) || {};
		} catch (e) {
			return {}; // required filter missing etc. — send what we can; server re-validates
		}
	}

	function openBrandedPdf() {
		var qr = frappe.query_report;
		var rn = qr && qr.report_name;
		if (!rn) {
			frappe.msgprint(__('Open a report first.'));
			return;
		}
		var url = '/api/method/lumenpdf.report.report_pdf'
			+ '?report_name=' + encodeURIComponent(rn)
			+ '&filters=' + encodeURIComponent(JSON.stringify(currentFilters(qr) || {}));
		window.open(url, '_blank');
	}

	function ensureButton() {
		try {
			if (!frappe.get_route || frappe.get_route()[0] !== 'query-report') return;
			var qr = frappe.query_report;
			if (!qr || !qr.page || !qr.page.wrapper) return;
			var $std = $(qr.page.wrapper).find('.page-actions .standard-actions').first();
			if (!$std.length) return;
			if ($std.find('[data-bpdf-btn]:visible').length) return; // alive and visible
			$std.find('[data-bpdf-btn]').remove();
			$('<button type="button" class="btn btn-default btn-sm" data-bpdf-btn="1" style="margin-right:6px">'
				+ __('Branded PDF') + '</button>')
				.on('click', openBrandedPdf)
				.prependTo($std);
		} catch (e) { /* never break the report view */ }
	}

	$(document).on('page-change', function () { setTimeout(ensureButton, 500); });
	$(document).ready(function () { setTimeout(ensureButton, 500); });
	setInterval(ensureButton, 1500);
})();
