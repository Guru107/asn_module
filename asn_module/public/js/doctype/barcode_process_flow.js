frappe.ui.form.on("Barcode Process Flow", {
	setup(frm) {
		const grid = frm.fields_dict.steps.grid;
		grid.get_field("mapping_set").get_query = () => ({ filters: { is_active: 1 } });
		grid.get_field("condition").get_query = () => ({ filters: { is_active: 1 } });
		grid.get_field("server_script").get_query = () => ({
			filters: { script_type: "API", disabled: 0 },
		});
	},

	refresh(frm) {
		frm.add_custom_button(__("Add Step From Standard Handler"), () =>
			open_standard_handler_picker(frm)
		);
	},
});

async function open_standard_handler_picker(frm) {
	const templates = await get_standard_handler_templates(frm);
	if (!templates.length) {
		frappe.msgprint(__("No standard handlers are available for this ERP version."));
		return;
	}

	const sourceOptions = Array.from(new Set(templates.map((row) => row.from_doctype))).sort();
	const dialog = new frappe.ui.Dialog({
		title: __("Add Step From Standard Handler"),
		fields: [
			{
				fieldname: "source_doctype",
				fieldtype: "Select",
				label: __("From DocType"),
				options: sourceOptions.join("\n"),
				reqd: 1,
			},
			{
				fieldname: "template_key",
				fieldtype: "Select",
				label: __("Standard Handler"),
				options: "",
				reqd: 1,
				description: __("Templates are filtered by selected From DocType."),
			},
			{
				fieldname: "to_doctype",
				fieldtype: "Data",
				label: __("To DocType"),
				read_only: 1,
			},
			{
				fieldname: "handler_path",
				fieldtype: "Data",
				label: __("Handler Path"),
				read_only: 1,
			},
			{
				fieldname: "mapping_set",
				fieldtype: "Link",
				options: "Barcode Mapping Set",
				label: __("Mapping Set"),
				reqd: 1,
				description: __(
					"Required by Flow Step validation. Runtime will still prefer standard handler for supported pairs."
				),
				get_query: () => ({ filters: { is_active: 1 } }),
			},
			{
				fieldname: "condition",
				fieldtype: "Link",
				options: "Barcode Rule",
				label: __("Condition"),
				get_query: () => ({ filters: { is_active: 1 } }),
			},
			{
				fieldname: "label",
				fieldtype: "Data",
				label: __("Step Label"),
			},
			{
				fieldname: "scan_action_key",
				fieldtype: "Data",
				label: __("Scan Action Key"),
			},
			{
				fieldname: "priority",
				fieldtype: "Int",
				label: __("Priority"),
				default: 100,
			},
			{
				fieldname: "generate_next_barcode",
				fieldtype: "Check",
				label: __("Generate Next Barcode"),
				default: 1,
			},
			{
				fieldname: "generation_mode",
				fieldtype: "Select",
				label: __("Generation Mode"),
				options: "immediate\nruntime\nhybrid",
				default: "hybrid",
				reqd: 1,
			},
			{
				fieldname: "doc_conditions_html",
				fieldtype: "HTML",
				label: __("Template Conditions"),
			},
		],
		primary_action_label: __("Add Step"),
		primary_action(values) {
			const template = find_template(templates, values.source_doctype, values.template_key);
			if (!template) {
				frappe.msgprint(__("Please choose a standard handler template."));
				return;
			}

			const row = frm.add_child("steps", {
				label:
					(values.label || "").trim() ||
					`${template.from_doctype} -> ${template.to_doctype}`,
				from_doctype: template.from_doctype,
				to_doctype: template.to_doctype,
				scan_action_key: (values.scan_action_key || "").trim() || template.key,
				execution_mode: "Mapping",
				mapping_set: values.mapping_set,
				condition: values.condition || "",
				priority: values.priority ?? 100,
				generate_next_barcode: values.generate_next_barcode ? 1 : 0,
				generation_mode: values.generation_mode || "hybrid",
				is_active: 1,
			});
			frm.refresh_field("steps");
			dialog.hide();
			frappe.show_alert(
				{
					message: __("Flow Step added: {0}", [
						row.label || `${row.from_doctype} -> ${row.to_doctype}`,
					]),
					indicator: "green",
				},
				5
			);
		},
	});

	const updateTemplateOptions = () => {
		const selectedSource = (dialog.get_value("source_doctype") || "").trim();
		const sourceTemplates = templates.filter((row) => row.from_doctype === selectedSource);
		const templateOptions = sourceTemplates.map((row) => row.key);
		dialog.set_df_property("template_key", "options", templateOptions.join("\n"));

		const defaultTemplateKey = templateOptions[0] || "";
		dialog.set_value("template_key", defaultTemplateKey);
		applyTemplateDetails();
	};

	const applyTemplateDetails = () => {
		const template = find_template(
			templates,
			dialog.get_value("source_doctype"),
			dialog.get_value("template_key")
		);
		if (!template) {
			dialog.set_value("to_doctype", "");
			dialog.set_value("handler_path", "");
			dialog.set_value("label", "");
			dialog.set_value("scan_action_key", "");
			dialog.fields_dict.doc_conditions_html.$wrapper.html(
				`<small>${__("No conditions.")}</small>`
			);
			return;
		}

		dialog.set_value("to_doctype", template.to_doctype);
		dialog.set_value("handler_path", template.handler);
		dialog.set_value("label", `${template.from_doctype} -> ${template.to_doctype}`);
		dialog.set_value("scan_action_key", template.key);
		dialog.fields_dict.doc_conditions_html.$wrapper.html(
			`<small>${frappe.utils.escape_html(
				format_doc_conditions(template.doc_conditions)
			)}</small>`
		);
	};

	dialog.show();
	dialog.fields_dict.source_doctype.$input.on("change", updateTemplateOptions);
	dialog.fields_dict.template_key.$input.on("change", applyTemplateDetails);
	dialog.set_value("source_doctype", sourceOptions[0] || "");
	updateTemplateOptions();
}

async function get_standard_handler_templates(frm) {
	if (Array.isArray(frm.standard_handler_templates)) {
		return frm.standard_handler_templates;
	}
	const response = await frappe.call("asn_module.setup_actions.get_standard_handler_templates");
	frm.standard_handler_templates = Array.isArray(response.message) ? response.message : [];
	return frm.standard_handler_templates;
}

function find_template(templates, fromDoctype, templateKey) {
	return templates.find((row) => row.from_doctype === fromDoctype && row.key === templateKey);
}

function format_doc_conditions(docConditions) {
	if (
		!docConditions ||
		typeof docConditions !== "object" ||
		!Object.keys(docConditions).length
	) {
		return __("No conditions. Applies to all source documents.");
	}

	const lines = [];
	Object.keys(docConditions)
		.sort()
		.forEach((fieldname) => {
			const values = Array.isArray(docConditions[fieldname]) ? docConditions[fieldname] : [];
			lines.push(`${fieldname}: ${values.join(", ")}`);
		});
	return __("Conditions: {0}", [lines.join(" | ")]);
}
