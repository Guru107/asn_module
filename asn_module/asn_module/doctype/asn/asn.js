frappe.ui.form.on("ASN", {
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
});

frappe.ui.form.on("ASN Item", {
	purchase_order(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.purchase_order) {
			return;
		}

		frappe.call({
			method: "asn_module.asn_module.doctype.asn.asn.get_purchase_order_items",
			args: { purchase_order: row.purchase_order, asn_name: frm.doc.name },
			callback(r) {
				if (!r.message || !r.message.length) {
					return;
				}

				const current_idx = row.idx;
				frm.doc.items = frm.doc.items.filter((d) => d.idx !== current_idx);

				r.message.forEach((item) => {
					const new_row = frm.add_child("items");
					Object.assign(new_row, item);
				});

				frm.refresh_field("items");
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
