/* global asn_module */

frappe.provide("asn_module");

asn_module.ScanDialog = class ScanDialog {
	constructor() {
		this.is_processing = false;
		this.dialog = new frappe.ui.Dialog({
			title: __("Scan QR Code"),
			fields: [
				{
					fieldname: "scan_input",
					fieldtype: "Data",
					label: __("Scan or paste code"),
					description: __("Scan the QR/barcode or paste the dispatch URL (code=) or raw short code"),
				},
			],
			primary_action_label: __("Process"),
			primary_action: (values) => {
				this.process_scan(values.scan_input);
			},
		});

		// Auto-submit on Enter in the input
		this.dialog.$wrapper.find('input[data-fieldname="scan_input"]').on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this.dialog.get_primary_btn().trigger("click");
			}
		});
	}

	show() {
		this.dialog.show();
		this.dialog.set_value("scan_input", "");
		setTimeout(() => {
			this.dialog.$wrapper.find('input[data-fieldname="scan_input"]').focus();
		}, 100);
	}

	parse_scan_input(value) {
		const input = (value || "").trim();
		if (!input) {
			return { error: __("Please scan or paste a scan code or dispatch URL.") };
		}

		try {
			const parsed = new URL(input, window.location.origin);
			if (parsed.searchParams.get("token")) {
				return {
					error: __(
						"This URL uses the old token format. Use the short code printed on the document."
					),
				};
			}

			const code_param = parsed.searchParams.get("code");
			if (code_param) {
				return { code: decodeURIComponent(code_param).trim() };
			}

			if (parsed.pathname && parsed.pathname.startsWith("/files/")) {
				return {
					error: __(
						"You pasted an image file URL. Scan the QR or barcode so the scanner sends the code or URL."
					),
				};
			}

			if (/^https?:\/\//i.test(input)) {
				return {
					error: __("Scanned URL is missing the code query parameter (expected ...dispatch?code=...)."),
				};
			}
		} catch (e) {
			// Not a URL. Treat as raw scan code.
		}

		return { code: input.replace(/[\s-]/g, "") };
	}

	process_scan(value) {
		if (this.is_processing || !value || !value.trim()) return;

		const parsed = this.parse_scan_input(value);
		if (parsed.error) {
			frappe.show_alert(
				{
					message: parsed.error,
					indicator: "orange",
				},
				6
			);
			return;
		}
		this.is_processing = true;
		const code = parsed.code;

		this.dialog.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { code: code, device_info: "Desktop" },
			callback: (r) => {
				this.is_processing = false;
				if (r.message && r.message.success) {
					frappe.show_alert(
						{
							message: __(r.message.message || "Document created"),
							indicator: "green",
						},
						5
					);
					frappe.set_route(r.message.url);
				}
			},
			error: () => {
				this.is_processing = false;
				frappe.show_alert(
					{
						message: __("Scan failed. Check Scan Log for details."),
						indicator: "red",
					},
					5
				);
			},
		});
	}
};
