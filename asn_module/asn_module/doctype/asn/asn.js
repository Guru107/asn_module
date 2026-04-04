frappe.ui.form.on("ASN", {
	onload(frm) {
		if (frm.__asn_trace_report_btn) {
			return;
		}
		frm.__asn_trace_report_btn = true;
		frm.add_custom_button(__("Open Full Trace View"), () => {
			if (!frm.doc.name || frm.is_new()) {
				frappe.show_alert({ message: __("Save the ASN first."), indicator: "orange" });
				return;
			}
			frappe.route_options = { asn: frm.doc.name };
			frappe.set_route("query-report", "ASN Item Transition Trace");
		});
	},

	setup(frm) {
		frm.set_query("purchase_order", "items", function () {
			return {
				filters: {
					supplier: frm.doc.supplier,
					docstatus: 1,
					status: ["in", ["To Receive and Bill", "To Receive"]],
				},
			};
		});

		frm.set_query("item_code", "items", function (_doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.purchase_order) {
				return {};
			}

			return {
				query: "asn_module.asn_module.doctype.asn.asn.get_po_items",
				filters: { purchase_order: row.purchase_order },
			};
		});
	},

	supplier(frm) {
		if (frm.doc.items && frm.doc.items.length) {
			frappe.confirm(
				__("Changing supplier will clear all items. Continue?"),
				function () {
					frm.clear_table("items");
					frm.refresh_field("items");
					frm.doc.__last_supplier = frm.doc.supplier;
				},
				function () {
					frm.set_value("supplier", frm.doc.__last_supplier || "");
				}
			);
			return;
		}

		frm.doc.__last_supplier = frm.doc.supplier;
	},

	refresh(frm) {
		if (!frm.fields_dict.asn_trace_summary || frm.is_new() || !frm.doc.name) {
			return;
		}
		frappe.call({
			method: "asn_module.asn_module.doctype.asn.asn.get_item_transition_summary",
			args: { asn: frm.doc.name },
			callback(r) {
				const rows = r.message || [];
				let html;
				if (!rows.length) {
					html = `<p class="text-muted small">${__("No transition events recorded yet.")}</p>`;
				} else {
					const th = (s) => frappe.utils.escape_html(s || "");
					html =
						'<div class="table-responsive"><table class="table table-bordered table-sm">' +
						"<thead><tr>" +
						`<th>${__("Item")}</th>` +
						`<th>${__("State")}</th>` +
						`<th>${__("Status")}</th>` +
						`<th>${__("Ref")}</th>` +
						`<th>${__("Updated")}</th>` +
						"</tr></thead><tbody>";
					rows.forEach((row) => {
						const item = th(row.item_code || row.asn_item || "");
						const st = th(row.state || "");
						const ts = th(row.transition_status || "");
						const ref = th(
							[row.ref_doctype, row.ref_name].filter(Boolean).join(" ").trim()
						);
						const when = row.event_ts ? th(frappe.datetime.str_to_user(row.event_ts)) : "";
						html += `<tr><td>${item}</td><td>${st}</td><td>${ts}</td><td>${ref}</td><td>${when}</td></tr>`;
					});
					html += "</tbody></table></div>";
				}
				frm.fields_dict.asn_trace_summary.$wrapper.html(html);
			},
		});
	},
});

frappe.ui.form.on("ASN Item", {
	purchase_order(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.purchase_order) {
			return;
		}
		// Rows generated from PO items already carry purchase_order_item; skip re-fetch loops.
		if (row.purchase_order_item) {
			return;
		}
		if (frm.__is_loading_po_items) {
			return;
		}
		frm.__is_loading_po_items = true;

		frappe.call({
			method: "asn_module.asn_module.doctype.asn.asn.get_purchase_order_items",
			args: { purchase_order: row.purchase_order, asn_name: frm.doc.name },
			callback(r) {
				try {
					if (!r.message || !r.message.length) {
						return;
					}

					const [first_item, ...remaining_items] = r.message;
					Object.assign(row, first_item);
					remaining_items.forEach((item) => {
						const new_row = frm.add_child("items");
						Object.assign(new_row, item);
					});

					frm.refresh_field("items");
				} finally {
					frm.__is_loading_po_items = false;
				}
			},
			error() {
				frm.__is_loading_po_items = false;
			},
		});
	},

	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.qty > 0) {
			return;
		}

		frappe.msgprint(__("Quantity must be greater than 0"));
		frappe.model.set_value(cdt, cdn, "qty", 1);
	},
});
