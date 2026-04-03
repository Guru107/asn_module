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
					label: __("Scan or paste token"),
					description: __("Use your scanner or paste the QR URL here"),
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

	parse_token_input(value) {
		const input = (value || "").trim();
		if (!input) {
			return { error: __("Please scan or paste a token value.") };
		}

		try {
			const parsed = new URL(input, window.location.origin);
			const token_param = parsed.searchParams.get("token");
			if (token_param) {
				return { token: decodeURIComponent(token_param) };
			}

			if (parsed.pathname && parsed.pathname.startsWith("/files/")) {
				return {
					error: __(
						"You pasted a QR image file URL. Scan the QR image content or paste the URL containing token."
					),
				};
			}

			if (/^https?:\/\//i.test(input)) {
				return { error: __("Scanned URL is missing token query parameter.") };
			}
		} catch (e) {
			// Not a URL. Treat as raw token.
		}

		return { token: input };
	}

	process_scan(value) {
		if (this.is_processing || !value || !value.trim()) return;

		const parsed = this.parse_token_input(value);
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
		const token = parsed.token;

		this.dialog.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { token: token, device_info: "Desktop" },
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
