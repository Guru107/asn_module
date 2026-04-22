frappe.ui.form.on("Barcode Process Flow", {
	setup(frm) {
		const grid = frm.fields_dict.steps.grid;
		grid.get_field("mapping_set").get_query = () => ({ filters: { is_active: 1 } });
		grid.get_field("condition").get_query = () => ({ filters: { is_active: 1 } });
		grid.get_field("server_script").get_query = () => ({ filters: { script_type: "API", disabled: 0 } });
	},
});
