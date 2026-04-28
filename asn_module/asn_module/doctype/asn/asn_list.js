frappe.listview_settings["ASN"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Bulk Upload ASN"), () => {
			show_asn_bulk_upload_dialog();
		});
	},
};

function show_asn_bulk_upload_dialog() {
	function format_error_message(error) {
		const response = error && error.responseJSON ? error.responseJSON : {};
		if (response._server_messages) {
			try {
				const messages = JSON.parse(response._server_messages).map((message) =>
					frappe.utils.escape_html(parse_server_message(message))
				);
				return messages.join("<br>");
			} catch {
				return response._server_messages;
			}
		}
		return (
			response.message ||
			(error && error.message) ||
			__("Bulk upload failed. Please try again.")
		);
	}

	function parse_server_message(message) {
		try {
			return JSON.parse(message).message || message;
		} catch {
			return message;
		}
	}

	function download_template() {
		frappe.call({
			method: "asn_module.asn_module.doctype.asn.bulk_upload.get_bulk_csv_headers",
			callback(r) {
				const headers = r.message || [];
				const blob = new Blob(["\ufeff", `${headers.join(",")}\n`], {
					type: "text/csv;charset=utf-8",
				});
				const url = URL.createObjectURL(blob);
				const anchor = document.createElement("a");
				anchor.href = url;
				anchor.download = "asn_bulk_upload_template.csv";
				document.body.appendChild(anchor);
				anchor.click();
				document.body.removeChild(anchor);
				URL.revokeObjectURL(url);
			},
			error(error) {
				frappe.msgprint({
					title: __("Download Failed"),
					indicator: "red",
					message: format_error_message(error),
				});
			},
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Upload ASN"),
		fields: [
			{
				fieldname: "supplier",
				fieldtype: "Link",
				label: __("Supplier"),
				options: "Supplier",
				reqd: 1,
				description: __("Select the supplier for the Sales Invoice being uploaded."),
			},
			{
				fieldname: "csv_file",
				fieldtype: "Attach",
				label: __("CSV File"),
				reqd: 1,
				description: __("Use the same CSV template as the supplier portal bulk upload."),
			},
			{
				fieldname: "download_template",
				fieldtype: "Button",
				label: __("Download Template"),
				click: download_template,
			},
		],
		primary_action_label: __("Create ASNs"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "asn_module.asn_module.doctype.asn.bulk_upload.create_from_csv_file",
				args: {
					file_url: values.csv_file,
					supplier: values.supplier,
				},
				callback(r) {
					const result = r.message || {};
					const names = result.asn_names || [];
					const links = names
						.map((name) => {
							const escaped = frappe.utils.escape_html(name);
							return `<a href="/app/asn/${encodeURIComponent(name)}">${escaped}</a>`;
						})
						.join(", ");
					frappe.msgprint({
						title: __("ASNs Created"),
						indicator: "green",
						message: __("Created {0} ASN(s): {1}", [
							result.created_count || names.length,
							links,
						]),
					});
					dialog.hide();
				},
				error(error) {
					frappe.msgprint({
						title: __("Bulk Upload Failed"),
						indicator: "red",
						message: format_error_message(error),
					});
				},
				always() {
					dialog.enable_primary_action();
				},
			});
		},
	});

	dialog.show();
}
