frappe.ui.form.on("Barcode Flow Transition", {
	setup(frm) {
		const flowFilters = () => {
			if (!frm.doc.flow) {
				return { filters: { name: ["=", ""] } };
			}
			return { filters: { flow: frm.doc.flow } };
		};

		frm.set_query("source_node", flowFilters);
		frm.set_query("target_node", flowFilters);
		frm.set_query("condition", flowFilters);
		frm.set_query("field_map", flowFilters);
		frm.set_query("action_binding", flowFilters);
		frm.set_query("action", () => ({ filters: { is_active: 1 } }));
	},
});
