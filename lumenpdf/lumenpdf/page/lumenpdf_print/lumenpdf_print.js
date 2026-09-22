// Copyright (c) 2026 Lumen Solutions (BSTC W.L.L). All rights reserved.
// SPDX-License-Identifier: LicenseRef-Lumen-Proprietary
// Proprietary and confidential. See license.txt. "LumenPDF" and "LumenPDF Studio" are
// trademarks of Lumen Solutions.
// Our own print screen, reached from the branded button on a document. It lists every format
// that document can print with, renders the SELECTED one to a real PDF and shows that file, so
// what is on screen is the file itself and not an approximation of it. Print, download and
// email all act on that same file. ERPNext's own print view stays one click away.

frappe.provide('lumenpdf.print');

frappe.pages['lumenpdf-print'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Print'),
		single_column: true,
	});
	lumenpdf.print.page = page;
	page.main.addClass('bpdf-print-host');
	page.main.html(lumenpdf.print.shell());
};

// The route carries the document: /app/lumenpdf-print/<doctype>/<name>
frappe.pages['lumenpdf-print'].on_page_show = function () {
	const route = frappe.get_route() || [];
	const doctype = route[1] ? decodeURIComponent(route[1]) : null;
	const name = route[2] ? decodeURIComponent(route[2]) : null;
	lumenpdf.print.load(doctype, name);
};

lumenpdf.print.shell = function () {
	return `
<style>
	.bpdf-print-host { --bpdf-line: var(--border-color, #e2e8f0); }
	.bpdf-wrap { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 16px; align-items: start; }
	.bpdf-side { border: 1px solid var(--bpdf-line); border-radius: 10px; background: var(--card-bg, #fff); overflow: hidden; }
	.bpdf-side h6 { margin: 0; padding: 11px 14px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
		color: var(--text-muted, #74808b); border-bottom: 1px solid var(--bpdf-line); font-weight: 600; }
	.bpdf-fmt { display: block; width: 100%; text-align: inherit; padding: 11px 14px; border: 0; background: none;
		border-bottom: 1px solid var(--bpdf-line); cursor: pointer; color: var(--text-color, #1f272e); }
	.bpdf-fmt:last-child { border-bottom: 0; }
	.bpdf-fmt:hover { background: var(--fg-hover-color, #f4f5f6); }
	.bpdf-fmt.on { background: var(--bg-blue, #f0f4ff); box-shadow: inset 3px 0 0 var(--blue-500, #1463ff); }
	.bpdf-fmt b { display: block; font-size: 13px; font-weight: 600; }
	.bpdf-fmt small { color: var(--text-muted, #74808b); font-size: 11px; }
	.bpdf-stage { border: 1px solid var(--bpdf-line); border-radius: 10px; background: var(--subtle-accent, #f4f5f6);
		min-height: calc(100vh - 220px); display: flex; align-items: center; justify-content: center; overflow: hidden; }
	.bpdf-stage iframe, .bpdf-stage embed { width: 100%; height: calc(100vh - 220px); border: 0; background: #fff; }
	.bpdf-msg { text-align: center; color: var(--text-muted, #74808b); font-size: 13px; padding: 40px 20px; }
	.bpdf-msg .bpdf-spin { width: 26px; height: 26px; margin: 0 auto 12px; border-radius: 50%;
		border: 2.5px solid var(--bpdf-line); border-top-color: var(--blue-500, #1463ff); animation: bpdfspin .8s linear infinite; }
	@keyframes bpdfspin { to { transform: rotate(360deg); } }
	.bpdf-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }
	.bpdf-bar .bpdf-doc { font-size: 13px; color: var(--text-muted, #74808b); }
	.bpdf-bar .bpdf-doc b { color: var(--text-color, #1f272e); }
	.bpdf-bar .spacer { flex: 1; }
	.bpdf-native { font-size: 12px; }
	@media (max-width: 900px) { .bpdf-wrap { grid-template-columns: minmax(0, 1fr); } }
</style>
<div class="bpdf-bar">
	<div class="bpdf-doc" id="bpdf-doc"></div>
	<div class="spacer"></div>
	<button class="btn btn-default btn-sm" id="bpdf-email">${frappe.utils.icon('mail', 'sm')} ${__('Email')}</button>
	<button class="btn btn-default btn-sm" id="bpdf-download">${frappe.utils.icon('down-arrow', 'sm')} ${__('Download PDF')}</button>
	<button class="btn btn-primary btn-sm" id="bpdf-print">${frappe.utils.icon('printer', 'sm')} ${__('Print')}</button>
</div>
<div class="bpdf-wrap">
	<div class="bpdf-side">
		<h6>${__('Formats')}</h6>
		<div id="bpdf-formats"></div>
		<div style="padding: 11px 14px; border-top: 1px solid var(--bpdf-line)">
			<a href="#" class="bpdf-native" id="bpdf-native">${__("Use ERPNext's own print view")}</a>
		</div>
	</div>
	<div class="bpdf-stage" id="bpdf-stage"></div>
</div>`;
};

lumenpdf.print.state = { doctype: null, name: null, formats: [], current: null, files: {}, job: null };

lumenpdf.print.load = function (doctype, name) {
	const S = lumenpdf.print.state;
	const page = lumenpdf.print.page;
	if (!page) return;
	if (!doctype || !name) {
		lumenpdf.print.stage(`<div class="bpdf-msg">${__('Open this screen from a document.')}</div>`);
		return;
	}
	// Same document as last time: keep the rendered files, do not pay for the render again.
	const same = S.doctype === doctype && S.name === name;
	S.doctype = doctype;
	S.name = name;
	if (!same) {
		S.formats = [];
		S.current = null;
		S.files = {};
	}
	page.set_title(__('Print') + ': ' + name);
	$('#bpdf-doc').html(`<b>${frappe.utils.escape_html(name)}</b> · ${frappe.utils.escape_html(__(doctype))}`);
	$('#bpdf-native').off('click').on('click', function (e) {
		e.preventDefault();
		frappe.set_route('print', doctype, name);
	});
	$('#bpdf-print').off('click').on('click', lumenpdf.print.doPrint);
	$('#bpdf-download').off('click').on('click', lumenpdf.print.doDownload);
	$('#bpdf-email').off('click').on('click', lumenpdf.print.doEmail);

	if (same && S.formats.length) {
		lumenpdf.print.paintFormats();
		lumenpdf.print.show(S.current);
		return;
	}
	lumenpdf.print.stage(`<div class="bpdf-msg"><div class="bpdf-spin"></div>${__('Loading formats...')}</div>`);
	frappe.call({
		method: 'lumenpdf.api.list_formats',
		args: { doctype: doctype },
		callback: function (r) {
			S.formats = r.message || [];
			if (!S.formats.length) {
				lumenpdf.print.stage(
					`<div class="bpdf-msg">${__('No LumenPDF format is set up for this document type yet.')}<br>
					<a href="/app/lumenpdf-builder">${__('Design one in LumenPDF Studio')}</a></div>`
				);
				$('#bpdf-formats').empty();
				return;
			}
			const def = S.formats.find((f) => f.is_default) || S.formats[0];
			lumenpdf.print.paintFormats();
			lumenpdf.print.select(def.name);
		},
	});
};

lumenpdf.print.paintFormats = function () {
	const S = lumenpdf.print.state;
	const host = $('#bpdf-formats').empty();
	S.formats.forEach(function (f) {
		const btn = $(
			`<button class="bpdf-fmt" data-fmt="${frappe.utils.escape_html(f.name)}">
				<b>${frappe.utils.escape_html(f.label || f.name)}</b>
				${f.is_default ? `<small>★ ${__('default')}</small>` : ''}
			</button>`
		);
		btn.toggleClass('on', f.name === S.current);
		btn.on('click', function () { lumenpdf.print.select(f.name); });
		host.append(btn);
	});
};

lumenpdf.print.select = function (fmt) {
	const S = lumenpdf.print.state;
	S.current = fmt;
	$('.bpdf-fmt').removeClass('on');
	$(`.bpdf-fmt[data-fmt="${fmt}"]`).addClass('on');
	if (S.files[fmt]) {
		lumenpdf.print.show(fmt);
		return;
	}
	lumenpdf.print.stage(`<div class="bpdf-msg"><div class="bpdf-spin"></div>${__('Rendering this format...')}</div>`);
	frappe.call({
		method: 'lumenpdf.api.request_pdf',
		args: { doctype: S.doctype, name: S.name, template: fmt },
		callback: function (r) {
			const job = (r.message || {}).job_id;
			if (!job) {
				lumenpdf.print.stage(`<div class="bpdf-msg">${__('Could not start the render.')}</div>`);
				return;
			}
			S.job = job;
			lumenpdf.print.poll(job, fmt, 0);
		},
		error: function () {
			lumenpdf.print.stage(`<div class="bpdf-msg">${__('Could not start the render.')}</div>`);
		},
	});
};

lumenpdf.print.poll = function (job, fmt, tries) {
	const S = lumenpdf.print.state;
	if (S.job !== job) return;  // the user moved on to another format
	if (tries > 80) {
		lumenpdf.print.stage(`<div class="bpdf-msg">${__('The render timed out.')}</div>`);
		return;
	}
	frappe.call({
		method: 'lumenpdf.api.get_job_result',
		args: { job_id: job },
		callback: function (r) {
			const s = r.message || {};
			if (S.job !== job) return;
			if (s.status === 'done' && s.file_url) {
				S.files[fmt] = { file_url: s.file_url, file_name: s.file_name, name: s.file_id };
				if (S.current === fmt) lumenpdf.print.show(fmt);
			} else if (s.status === 'error') {
				lumenpdf.print.stage(
					`<div class="bpdf-msg">${frappe.utils.escape_html(s.message || __('The render failed.'))}</div>`
				);
			} else {
				setTimeout(function () { lumenpdf.print.poll(job, fmt, tries + 1); }, 1200);
			}
		},
		error: function () {
			lumenpdf.print.stage(`<div class="bpdf-msg">${__('The render failed.')}</div>`);
		},
	});
};

lumenpdf.print.show = function (fmt) {
	const f = lumenpdf.print.state.files[fmt];
	const url = f && f.file_url;
	if (!url) return;
	// #toolbar=0 hides the viewer's own chrome in Chrome; harmless elsewhere.
	lumenpdf.print.stage(`<iframe id="bpdf-frame" src="${frappe.utils.escape_html(url)}#toolbar=0&navpanes=0" title="${__('Preview')}"></iframe>`);
};

lumenpdf.print.stage = function (html) {
	$('#bpdf-stage').html(html);
};

lumenpdf.print.file = function () {
	const S = lumenpdf.print.state;
	const f = S.files[S.current];
	if (!f) frappe.msgprint(__('The document is still rendering.'));
	return f;
};

lumenpdf.print.doDownload = function () {
	const f = lumenpdf.print.file();
	if (f) window.open(f.file_url, '_blank');
};

lumenpdf.print.doPrint = function () {
	const f = lumenpdf.print.file();
	if (!f) return;
	// Print the PDF itself, so the paper matches the file exactly. A cross-origin-free
	// same-site iframe can be driven directly; if the viewer blocks it, the tab still opens.
	const frame = document.getElementById('bpdf-frame');
	try {
		if (frame && frame.contentWindow) {
			frame.contentWindow.focus();
			frame.contentWindow.print();
			return;
		}
	} catch (e) {
		// fall through
	}
	window.open(f.file_url, '_blank');
};

lumenpdf.print.doEmail = function () {
	const S = lumenpdf.print.state;
	const f = lumenpdf.print.file();
	if (!f) return;
	// ERPNext's own composer, with our file attached and already ticked: the person keeps the
	// email screen they know. It attaches by File record, which is why the render returns one.
	new frappe.views.CommunicationComposer({
		doctype: S.doctype,
		name: S.name,
		subject: __(S.doctype) + ': ' + S.name,
		attach_document_print: false,
		attachments: [f],
	});
};
