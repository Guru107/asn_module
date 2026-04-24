frappe.ui.form.on("Barcode Mapping Set", {
	setup(frm) {
		frm.__mappable_field_options = {};
		void refresh_row_field_options(frm);
	},

	refresh(frm) {
		void refresh_row_field_options(frm);
	},

	source_doctype(frm) {
		void refresh_row_field_options(frm);
	},

	target_doctype(frm) {
		void refresh_row_field_options(frm);
	},
});

async function refresh_row_field_options(frm) {
	const grid = frm.fields_dict.rows && frm.fields_dict.rows.grid;
	if (!grid) {
		return;
	}

	const [sourceOptions, targetOptions] = await Promise.all([
		get_mappable_field_options(frm, frm.doc.source_doctype),
		get_mappable_field_options(frm, frm.doc.target_doctype),
	]);

	const sourceOptionsText = build_select_options(sourceOptions);
	const targetOptionsText = build_select_options(targetOptions);
	update_child_field_options(frm, grid, "source_field", sourceOptionsText);
	update_child_field_options(frm, grid, "target_field", targetOptionsText);
	grid.update_docfield_property("source_field", "options", sourceOptionsText);
	grid.update_docfield_property("target_field", "options", targetOptionsText);

	const sourceAllowed = new Set(sourceOptions);
	const targetAllowed = new Set(targetOptions);
	let changed = false;
	for (const row of frm.doc.rows || []) {
		if (row.source_field && !sourceAllowed.has(row.source_field)) {
			row.source_field = "";
			changed = true;
		}
		if (row.target_field && !targetAllowed.has(row.target_field)) {
			row.target_field = "";
			changed = true;
		}
	}
	if (changed) {
		frm.dirty();
	}
	frm.refresh_field("rows");
}

function build_select_options(options) {
	const normalized = Array.isArray(options) ? options.filter(Boolean) : [];
	return ["", ...normalized].join("\n");
}

function update_child_field_options(frm, grid, fieldname, optionsText) {
	const childDf = frappe.meta.get_docfield("Barcode Mapping Row", fieldname, frm.doc.name);
	if (childDf) {
		childDf.options = optionsText;
	}

	for (const gridRow of grid.grid_rows || []) {
		const inlineControl =
			gridRow.on_grid_fields_dict && gridRow.on_grid_fields_dict[fieldname];
		if (inlineControl) {
			inlineControl.df.options = optionsText;
			inlineControl.refresh();
		}

		const formControl = gridRow.grid_form && gridRow.grid_form.fields_dict[fieldname];
		if (formControl) {
			formControl.df.options = optionsText;
			formControl.refresh();
		}
	}
}

async function get_mappable_field_options(frm, parentDoctype) {
	const normalizedParent = (parentDoctype || "").trim();
	if (!normalizedParent) {
		return [];
	}

	frm.__mappable_field_options = frm.__mappable_field_options || {};
	if (Array.isArray(frm.__mappable_field_options[normalizedParent])) {
		return frm.__mappable_field_options[normalizedParent];
	}

	try {
		const response = await frappe.call({
			method: "asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set.get_mappable_field_options",
			args: {
				parent_doctype: normalizedParent,
			},
		});
		const options = Array.isArray(response.message) ? response.message : [];
		frm.__mappable_field_options[normalizedParent] = options;
		return options;
	} catch (error) {
		frappe.msgprint(__("Unable to load mappable field options."));
		console.error(error);
		return [];
	}
}
