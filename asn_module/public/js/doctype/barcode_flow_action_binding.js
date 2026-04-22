frappe.ui.form.on("Barcode Flow Action Binding", {
	setup(frm) {
		const flowFilters = () => ({ filters: { flow: frm.doc.flow || "" } });

		frm.set_query("target_node", flowFilters);
		frm.set_query("target_transition", flowFilters);
		frm.set_query("action", () => ({ filters: { is_active: 1 } }));
	},
});
