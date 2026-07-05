// Desk host for the visual format builder. Loads the builder (static asset) in an iframe and
// bridges Save/Load to lumenpdf.api over postMessage. Origin + source checked (review hardening).
function _bpdfPreviewPoll(job, tries) {
	if (tries > 80) { frappe.dom.unfreeze(); frappe.msgprint(__('Preview timed out.')); return; }
	frappe.call({
		method: 'lumenpdf.api.get_job_result',
		args: { job_id: job },
		callback: function (r) {
			var s = r.message || {};
			if (s.status === 'done' && s.file_url) { frappe.dom.unfreeze(); window.open(s.file_url, '_blank'); }
			else if (s.status === 'error') { frappe.dom.unfreeze(); frappe.msgprint(__(s.message || 'Preview failed.')); }
			else { setTimeout(function () { _bpdfPreviewPoll(job, tries + 1); }, 1500); }
		},
		error: function () { frappe.dom.unfreeze(); },
	});
}
frappe.pages['lumenpdf-builder'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'LumenPDF Studio',
		single_column: true,
	});
	var origin = window.location.origin;

	var iframe = document.createElement('iframe');
	iframe.src = '/assets/lumenpdf/builder/index.html';
	iframe.setAttribute('allowfullscreen', '');
	var IFRAME_CSS = 'width:100%;height:calc(100vh - 110px);border:0;background:#F4F6FA;border-radius:8px';
	iframe.style.cssText = IFRAME_CSS;
	page.main.append(iframe);

	// Push the active design + the doctype's full field list into the builder once it loads.
	iframe.addEventListener('load', function () {
		frappe.call({
			method: 'lumenpdf.api.get_format',
			callback: function (r) {
				var def = r.message && r.message.definition;
				var target = (def && def.target_doctype) || 'Quotation';
				if (def) {
					iframe.contentWindow.postMessage({ type: 'lumenpdf-load', definition: def }, origin);
				}
				frappe.call({
					method: 'lumenpdf.api.doctype_fields',
					args: { doctype: target },
					callback: function (f) {
						iframe.contentWindow.postMessage(
							{ type: 'lumenpdf-fields', fields: f.message || [] },
							origin
						);
					},
				});
			},
		});
	});

	// Generic RPC + save bridge — only accept messages from OUR iframe at OUR origin, and only
	// allow-listed read/save methods.
	var ALLOWED = {
		'lumenpdf.api.builder_doctypes': 1, 'lumenpdf.api.builder_docs': 1, 'lumenpdf.api.builder_sample': 1,
		'lumenpdf.api.doctype_fields': 1, 'lumenpdf.api.child_tables': 1, 'lumenpdf.api.list_formats': 1, 'lumenpdf.api.get_format': 1,
		'lumenpdf.api.save_format': 1, 'lumenpdf.api.set_default_format': 1, 'lumenpdf.api.delete_format': 1,
		'lumenpdf.api.list_companies': 1,
	};
	window.addEventListener('message', function (e) {
		if (e.origin !== origin) return;
		if (e.source !== iframe.contentWindow) return;
		var d = e.data || {};
		if (d.type === 'lumenpdf-rpc' && ALLOWED[d.method]) {
			frappe.call({
				method: d.method, args: d.args || {},
				callback: function (r) {
					iframe.contentWindow.postMessage({ type: 'lumenpdf-rpc-res', reqId: d.reqId, ok: true, message: r.message }, origin);
				},
				error: function () {
					iframe.contentWindow.postMessage({ type: 'lumenpdf-rpc-res', reqId: d.reqId, ok: false }, origin);
				},
			});
		} else if (d.type === 'lumenpdf-save') {
			frappe.call({
				method: 'lumenpdf.api.save_format',
				args: { definition: JSON.stringify(d.definition) },
				callback: function () {
					frappe.show_alert({ message: __('Format saved'), indicator: 'green' });
					iframe.contentWindow.postMessage({ type: 'lumenpdf-saved' }, origin);
				},
				error: function () {
					iframe.contentWindow.postMessage({ type: 'lumenpdf-saved', error: true }, origin);
				},
			});
		} else if (d.type === 'lumenpdf-fullscreen') {
			// expand the iframe over the whole viewport (covers the desk navbar) and back
			if (d.on) {
				iframe.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:1055;background:#F4F6FA';
			} else {
				iframe.style.cssText = IFRAME_CSS;
			}
		} else if (d.type === 'lumenpdf-preview') {
			frappe.dom.freeze(__('Rendering preview…'));
			frappe.call({
				method: 'lumenpdf.api.request_preview',
				args: { definition: JSON.stringify(d.definition), doctype: d.doctype, name: d.name || '' },
				callback: function (r) {
					var job = r.message && r.message.job_id;
					if (!job) { frappe.dom.unfreeze(); frappe.msgprint(__('Could not start preview.')); return; }
					_bpdfPreviewPoll(job, 0);
				},
				error: function () { frappe.dom.unfreeze(); },
			});
		} else if (d.type === 'lumenpdf-upload') {
			try {
				new frappe.ui.FileUploader({
					dialog_title: __('Upload image'),
					allow_multiple: false,
					make_attachments_public: true,
					restrictions: { allowed_file_types: ['image/*'] },
					on_success: function (file_doc) {
						iframe.contentWindow.postMessage(
							{ type: 'lumenpdf-upload-res', reqId: d.reqId, file_url: file_doc.file_url },
							origin
						);
					},
				});
			} catch (e) {
				frappe.msgprint(__('Upload is not available on this page.'));
			}
		}
	});
};
