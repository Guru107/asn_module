/* global asn_module */
frappe.pages["scan-station"].on_page_load = function (wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Scan Station"),
		single_column: true,
	});

	page.main.html(frappe.render_template("scan_station"));

	const $input = page.main.find(".scan-input");
	const $status = page.main.find(".scan-status");
	const $error = page.main.find(".scan-error");
	const $history = page.main.find(".scan-history-list");

	let scan_code_length = 16;
	let scan_timeout = null;

	asn_module.load_scan_code_length((length) => {
		scan_code_length = length;
	});

	// A printed QR opens this page with ?code=. Fill the code in but let the user confirm:
	// dispatching on page load would let any link do it under their name.
	function prefill_from_url() {
		const code = frappe.route_options && frappe.route_options.code;
		if (!code) return;
		delete frappe.route_options.code;
		$input.val(code).focus();
	}

	page.set_primary_action(__("Process Scan"), () => process_scan($input.val()));

	function process_scan(value) {
		if (!value || !value.trim()) return;

		const parsed = asn_module.parse_scan_input(value, {
			file: __(
				"You pasted an image file URL. Scan the QR or barcode so the scanner sends the code or Scan Station URL."
			),
			missing_code: __(
				"Scanned URL is missing the code query parameter. Expected ...scan-station?code=..."
			),
		});
		if (parsed.error) {
			$error.text(parsed.error).show();
			setTimeout(() => $error.fadeOut(), 5000);
			return;
		}
		const code = parsed.code;

		$input.prop("disabled", true);
		$status.show();
		$error.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { code: code, device_info: "Desktop" },
			callback(r) {
				$status.hide();
				$input.val("").prop("disabled", false).focus();

				if (r.message && r.message.success) {
					const doc_link = r.message.url
						? ` <a href="${frappe.utils.escape_html(
								r.message.url
						  )}">${frappe.utils.escape_html(r.message.name || r.message.url)}</a>`
						: "";
					frappe.show_alert(
						{
							message:
								frappe.utils.escape_html(
									r.message.message || __("Document created")
								) + doc_link,
							indicator: "green",
						},
						5
					);
					// Stay on the station; refresh history so the new scan shows up.
					load_scan_history();
				}
			},
			error(r) {
				$status.hide();
				$input.val("").prop("disabled", false).focus();

				$error.text(get_error_message(r)).show();
				setTimeout(() => $error.fadeOut(), 5000);
			},
		});
	}

	// frappe.call passes parsed JSON (417), an xhr (other statuses) or nothing (500/502/504).
	function get_error_message(r) {
		const body = (r && r.responseJSON) || r || {};
		try {
			const messages = JSON.parse(body._server_messages || "[]");
			if (messages.length) {
				return messages.map((m) => JSON.parse(m).message).join(" ");
			}
		} catch (e) {
			// fall through to the generic message
		}
		// Plain `raise` (no frappe.throw) only fills `exception`: "pkg.Error: message".
		const exc =
			typeof body.exception === "string"
				? body.exception.split(": ").slice(1).join(": ")
				: "";
		return exc || __("Scan failed. Please try again.");
	}

	// Handle scanner input (rapid keystrokes ending with Enter)
	$input.on("keydown", function (e) {
		if (e.key === "Enter") {
			e.preventDefault();
			clearTimeout(scan_timeout);
			process_scan($input.val());
		}
	});

	// Auto-submit after 300ms of no input (for scanners that don't send Enter)
	$input.on("input", function () {
		clearTimeout(scan_timeout);
		scan_timeout = setTimeout(() => {
			let val = $input.val();
			// Canonical raw scan codes or full Scan Station URLs with code=
			if (val && (val.length >= scan_code_length || /^https?:\/\//i.test(val))) {
				process_scan(val);
			}
		}, 300);
	});

	// Load recent scan history
	function load_scan_history() {
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Scan Log",
				fields: [
					"name",
					"scan_timestamp",
					"action",
					"result",
					"result_doctype",
					"result_name",
					"error_message",
				],
				filters: { user: frappe.session.user },
				order_by: "creation desc",
				limit_page_length: 20,
			},
			callback(r) {
				if (r.message) {
					render_scan_history(r.message);
				}
			},
			error() {
				$history.html(
					`<p class="text-muted text-center">${frappe.utils.escape_html(
						__("Unable to load scan history")
					)}</p>`
				);
			},
		});
	}

	function render_scan_history(logs) {
		if (!logs.length) {
			$history.html('<p class="text-muted text-center">' + __("No recent scans") + "</p>");
			return;
		}

		let html = '<div class="list-group">';
		logs.forEach((log) => {
			const safeAction = frappe.utils.escape_html(log.action || "");
			const safeError = frappe.utils.escape_html(log.error_message || "");
			let indicator = log.result === "Success" ? "green" : "red";
			let link =
				log.result === "Success" && log.result_doctype && log.result_name
					? `/app/${frappe.router.slug(log.result_doctype)}/${encodeURIComponent(
							log.result_name
					  )}`
					: "#";

			html += `
				<a href="${link}" class="list-group-item list-group-item-action">
					<div class="d-flex justify-content-between">
						<span class="indicator-pill ${indicator}">${safeAction}</span>
						<small class="text-muted">${frappe.datetime.prettyDate(log.scan_timestamp)}</small>
					</div>
					${log.error_message ? `<small class="text-danger">${safeError}</small>` : ""}
				</a>
			`;
		});
		html += "</div>";
		$history.html(html);
	}

	load_scan_history();

	prefill_from_url();

	// Refocus input when page becomes visible
	$(wrapper).on("show", () => {
		prefill_from_url();
		$input.focus();
	});
};
