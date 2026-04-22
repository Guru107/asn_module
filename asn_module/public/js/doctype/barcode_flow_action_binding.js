frappe.ui.form.on("Barcode Flow Action Binding", {
	setup(frm) {
		const flowFilters = () => {
			if (!frm.doc.flow) {
				return { filters: { name: ["=", ""] } };
			}
			return { filters: { flow: frm.doc.flow } };
		};

		frm.set_query("target_node", flowFilters);
		frm.set_query("target_transition", flowFilters);
		frm.set_query("action", () => ({ filters: { is_active: 1 } }));
	},
});
