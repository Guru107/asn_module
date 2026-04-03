/* global asn_module */

$(document).ready(function () {
	// Global scan shortcut: Ctrl+Shift+S
	frappe.ui.keys.add_shortcut({
		shortcut: "ctrl+shift+s",
		action: function () {
			if (!asn_module._scan_dialog) {
				asn_module._scan_dialog = new asn_module.ScanDialog();
			}
			asn_module._scan_dialog.show();
		},
		description: __("Open QR Scan Dialog"),
		page: undefined,
	});
});
