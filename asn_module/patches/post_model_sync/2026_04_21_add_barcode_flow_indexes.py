import frappe


UNIQUE_INDEX_SPECS = (
	("Barcode Flow Node", ("flow", "node_key"), "uniq_bf_node_flow_key"),
	("Barcode Flow Condition", ("flow", "condition_key"), "uniq_bf_condition_flow_key"),
	("Barcode Flow Field Map", ("flow", "map_key"), "uniq_bf_field_map_flow_key"),
	("Barcode Flow Action Binding", ("flow", "binding_key"), "uniq_bf_binding_flow_key"),
	("Barcode Flow Transition", ("flow", "transition_key"), "uniq_bf_transition_flow_key"),
)

NON_UNIQUE_INDEX_SPECS = (
	("Barcode Flow Transition", ("flow", "source_node", "priority"), "idx_bf_transition_flow_source_priority"),
)


def execute():
	for doctype, fields, index_name in UNIQUE_INDEX_SPECS:
		frappe.db.add_unique(doctype, fields, constraint_name=index_name)

	for doctype, fields, index_name in NON_UNIQUE_INDEX_SPECS:
		frappe.db.add_index(doctype, list(fields), index_name=index_name)


def verify_indexes():
	missing = []
	verified = {}

	for doctype, _, index_name in UNIQUE_INDEX_SPECS + NON_UNIQUE_INDEX_SPECS:
		table_name = f"tab{doctype}"
		exists = bool(frappe.db.has_index(table_name, index_name))
		verified[index_name] = exists
		if not exists:
			missing.append(index_name)

	if missing:
		frappe.throw(f"Missing barcode flow indexes: {', '.join(sorted(missing))}")

	return verified
