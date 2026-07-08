// Desk host for the visual format builder. Loads the builder (static asset) in an iframe and
// bridges Save/Load to brandpdf.api over postMessage. Origin + source checked (review hardening).
function _bpdfPreviewPoll(job, tries) {
	if (tries > 80) { frappe.dom.unfreeze(); frappe.msgprint(__('Preview timed out.')); return; }
	frappe.call({
		method: 'brandpdf.api.get_job_result',
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
frappe.pages['brandpdf-builder'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'LumenPDF Studio',
		single_column: true,
	});
	var origin = window.location.origin;

	var iframe = document.createElement('iframe');
	iframe.src = '/assets/brandpdf/builder/index.html';
	iframe.setAttribute('allowfullscreen', '');
	var IFRAME_CSS = 'width:100%;height:calc(100vh - 110px);border:0;background:#F4F6FA;border-radius:8px';
	iframe.style.cssText = IFRAME_CSS;
	page.main.append(iframe);

	// Dark mode: mirror the user's Frappe theme into the builder iframe, and keep it in sync.
	function bpdfTheme() {
		return document.documentElement.getAttribute('data-theme')
			|| (document.body.classList.contains('dark') ? 'dark' : 'light');
	}
	function pushTheme() {
		try { iframe.contentWindow.postMessage({ type: 'brandpdf-theme', theme: bpdfTheme() }, origin); } catch (e) {}
	}
	try {
		new MutationObserver(pushTheme).observe(document.documentElement, {
			attributes: true, attributeFilter: ['data-theme'],
		});
	} catch (e) {}

	// Push the active design + the doctype's full field list into the builder once it loads.
	iframe.addEventListener('load', function () {
		pushTheme();  // apply the current theme immediately on load
		frappe.call({
			method: 'brandpdf.api.get_format',
			callback: function (r) {
				var def = r.message && r.message.definition;
				var target = (def && def.target_doctype) || 'Quotation';
				if (def) {
					iframe.contentWindow.postMessage({ type: 'brandpdf-load', definition: def }, origin);
				}
				frappe.call({
					method: 'brandpdf.api.doctype_fields',
					args: { doctype: target },
					callback: function (f) {
						iframe.contentWindow.postMessage(
							{ type: 'brandpdf-fields', fields: f.message || [] },
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
		'brandpdf.api.builder_doctypes': 1, 'brandpdf.api.builder_docs': 1, 'brandpdf.api.builder_sample': 1,
		'brandpdf.api.doctype_fields': 1, 'brandpdf.api.doctype_link_fields': 1, 'brandpdf.api.child_tables': 1, 'brandpdf.api.list_formats': 1, 'brandpdf.api.get_format': 1,
		'brandpdf.api.save_format': 1, 'brandpdf.api.set_default_format': 1, 'brandpdf.api.delete_format': 1, 'brandpdf.api.duplicate_format': 1,
		'brandpdf.api.list_companies': 1, 'brandpdf.api.set_gallery': 1, 'brandpdf.api.gallery_list': 1,
		'brandpdf.api.builder_reports': 1, 'brandpdf.report.report_sample': 1, 'brandpdf.api.set_default_report_format': 1,
	};
	window.addEventListener('message', function (e) {
		if (e.origin !== origin) return;
		if (e.source !== iframe.contentWindow) return;
		var d = e.data || {};
		if (d.type === 'brandpdf-rpc' && ALLOWED[d.method]) {
			frappe.call({
				method: d.method, args: d.args || {},
				callback: function (r) {
					iframe.contentWindow.postMessage({ type: 'brandpdf-rpc-res', reqId: d.reqId, ok: true, message: r.message }, origin);
				},
				error: function () {
					iframe.contentWindow.postMessage({ type: 'brandpdf-rpc-res', reqId: d.reqId, ok: false }, origin);
				},
			});
		} else if (d.type === 'brandpdf-save') {
			frappe.call({
				method: 'brandpdf.api.save_format',
				args: { definition: JSON.stringify(d.definition) },
				callback: function () {
					frappe.show_alert({ message: __('Format saved'), indicator: 'green' });
					iframe.contentWindow.postMessage({ type: 'brandpdf-saved' }, origin);
				},
				error: function () {
					iframe.contentWindow.postMessage({ type: 'brandpdf-saved', error: true }, origin);
				},
			});
		} else if (d.type === 'brandpdf-fullscreen') {
			// expand the iframe over the whole viewport (covers the desk navbar) and back
			if (d.on) {
				iframe.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:1055;background:#F4F6FA';
			} else {
				iframe.style.cssText = IFRAME_CSS;
			}
		} else if (d.type === 'brandpdf-preview-report') {
			// Report preview: re-run the report server-side and render the UNSAVED design.
			// Hard client timeout: the UI must never stay frozen on a slow/stuck render.
			frappe.dom.freeze(__('Rendering report preview…'));
			var ac = (typeof AbortController !== 'undefined') ? new AbortController() : null;
			var timer = setTimeout(function () { if (ac) ac.abort(); }, 120000);
			fetch('/api/method/brandpdf.report.report_pdf', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': frappe.csrf_token },
				body: JSON.stringify({ report_name: d.report_name, definition: JSON.stringify(d.definition), preview: 1 }),
				signal: ac ? ac.signal : undefined,
			}).then(function (r) {
				clearTimeout(timer); frappe.dom.unfreeze();
				if (!r.ok) {
					return r.json().catch(function () { return {}; }).then(function (j) {
						var msg = '';
						try { msg = JSON.parse(JSON.parse(j._server_messages)[0]).message; } catch (e) {}
						frappe.msgprint(__(msg || 'Report preview failed.'));
					});
				}
				return r.blob().then(function (b) { window.open(URL.createObjectURL(b), '_blank'); });
			}).catch(function (err) {
				clearTimeout(timer); frappe.dom.unfreeze();
				var timedOut = err && (err.name === 'AbortError');
				frappe.msgprint(__(timedOut
					? 'The preview is taking too long. The first landscape render can be slow — try again in a minute (the engine remembers the fast path), or use the report\'s Branded PDF button.'
					: 'Report preview failed.'));
			});
		} else if (d.type === 'brandpdf-preview') {
			frappe.dom.freeze(__('Rendering preview…'));
			frappe.call({
				method: 'brandpdf.api.request_preview',
				args: { definition: JSON.stringify(d.definition), doctype: d.doctype, name: d.name || '' },
				callback: function (r) {
					var job = r.message && r.message.job_id;
					if (!job) { frappe.dom.unfreeze(); frappe.msgprint(__('Could not start preview.')); return; }
					_bpdfPreviewPoll(job, 0);
				},
				error: function () { frappe.dom.unfreeze(); },
			});
		} else if (d.type === 'brandpdf-upload') {
			try {
				new frappe.ui.FileUploader({
					dialog_title: __('Upload image'),
					allow_multiple: false,
					make_attachments_public: true,
					restrictions: { allowed_file_types: ['image/*'] },
					on_success: function (file_doc) {
						iframe.contentWindow.postMessage(
							{ type: 'brandpdf-upload-res', reqId: d.reqId, file_url: file_doc.file_url },
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
