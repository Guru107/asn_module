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

	frappe.call({
		method: "asn_module.qr_engine.scan_codes.get_scan_code_length",
		callback(r) {
			const value = Number(r.message);
			if (Number.isInteger(value) && value > 0) {
				scan_code_length = value;
			}
		},
	});

	function parse_scan_input(value) {
		const input = (value || "").trim();
		if (!input) {
			return { error: __("Please scan or paste a scan code or dispatch URL.") };
		}

		try {
			const parsed = new URL(input, window.location.origin);
			const code_param = parsed.searchParams.get("code");
			if (code_param) {
				return { code: decodeURIComponent(code_param).trim() };
			}

			if (parsed.pathname && parsed.pathname.startsWith("/files/")) {
				return {
					error: __(
						"You pasted an image file URL. Scan the QR or barcode so the scanner sends the code or dispatch URL."
					),
				};
			}

			if (/^https?:\/\//i.test(input)) {
				return {
					error: __(
						"Scanned URL is missing the code query parameter. Expected ...dispatch?code=..."
					),
				};
			}
		} catch (e) {
			// Not a URL. Treat as raw scan code.
		}

		return { code: input.replace(/\s/g, "") };
	}

	function process_scan(value) {
		if (!value || !value.trim()) return;

		const parsed = parse_scan_input(value);
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
					frappe.show_alert(
						{
							message: __(r.message.message || "Document created"),
							indicator: "green",
						},
						5
					);
					// Navigate to created document
					frappe.set_route(r.message.url);
				}
			},
			error(r) {
				$status.hide();
				$input.val("").prop("disabled", false).focus();

				let error_msg = r.responseJSON
					? r.responseJSON._server_messages || r.responseJSON.message
					: __("Scan failed. Please try again.");

				$error.text(error_msg).show();
				setTimeout(() => $error.fadeOut(), 5000);
			},
		});
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
			// Canonical raw scan codes or full dispatch URLs with code=
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

	// Refocus input when page becomes visible
	$(wrapper).on("show", () => $input.focus());
};
