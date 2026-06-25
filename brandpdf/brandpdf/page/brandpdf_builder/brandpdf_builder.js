// Desk host for the visual format builder. Loads the builder (static asset) in an iframe and
// bridges Save/Load to brandpdf.api over postMessage. Origin + source checked (review hardening).
frappe.pages['brandpdf-builder'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'BrandPDF Builder',
		single_column: true,
	});
	var origin = window.location.origin;

	var iframe = document.createElement('iframe');
	iframe.src = '/assets/brandpdf/builder/index.html';
	iframe.style.cssText =
		'width:100%;height:calc(100vh - 110px);border:0;background:#0f1420;border-radius:8px';
	page.main.append(iframe);

	// Push the currently-active design into the builder once it loads.
	iframe.addEventListener('load', function () {
		frappe.call({
			method: 'brandpdf.api.get_format',
			callback: function (r) {
				if (r.message && r.message.definition) {
					iframe.contentWindow.postMessage(
						{ type: 'brandpdf-load', definition: r.message.definition },
						origin
					);
				}
			},
		});
	});

	// Save bridge — only accept messages from OUR iframe at OUR origin.
	window.addEventListener('message', function (e) {
		if (e.origin !== origin) return;
		if (e.source !== iframe.contentWindow) return;
		var d = e.data || {};
		if (d.type === 'brandpdf-save') {
			frappe.call({
				method: 'brandpdf.api.save_format',
				args: { definition: JSON.stringify(d.definition) },
				callback: function () {
					frappe.show_alert({ message: __('Format saved & activated'), indicator: 'green' });
					iframe.contentWindow.postMessage({ type: 'brandpdf-saved' }, origin);
				},
			});
		}
	});
};
