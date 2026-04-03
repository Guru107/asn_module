/* global asn_module */

frappe.provide("asn_module");

asn_module.ScanDialog = class ScanDialog {
	constructor() {
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
				this.process_scan(this.dialog.get_value("scan_input"));
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

	process_scan(value) {
		if (!value || !value.trim()) return;

		let token = value.trim();
		let url_match = token.match(/[?&]token=([^&]+)/);
		if (url_match) {
			token = url_match[1];
		}

		this.dialog.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { token: token, device_info: "Desktop" },
			callback(r) {
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
			error() {
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
