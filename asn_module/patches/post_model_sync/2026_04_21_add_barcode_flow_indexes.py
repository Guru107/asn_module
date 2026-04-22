import frappe
from frappe.utils import get_table_name


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
		_add_unique_index(doctype, fields, index_name)

	for doctype, fields, index_name in NON_UNIQUE_INDEX_SPECS:
		_add_non_unique_index(doctype, fields, index_name)


def _add_unique_index(doctype, fields, index_name):
	if _index_exists(doctype, index_name):
		return

	table_name = _quote_table_name(doctype)
	columns = ", ".join(_quote_identifier(field) for field in fields)
	frappe.db.sql(f"ALTER TABLE {table_name} ADD UNIQUE {_quote_identifier(index_name)} ({columns})")


def _add_non_unique_index(doctype, fields, index_name):
	if _index_exists(doctype, index_name):
		return

	table_name = _quote_table_name(doctype)
	columns = ", ".join(_quote_identifier(field) for field in fields)
	frappe.db.sql(f"ALTER TABLE {table_name} ADD INDEX {_quote_identifier(index_name)} ({columns})")


def _index_exists(doctype, index_name):
	table_name = get_table_name(doctype)
	if frappe.db.db_type != "mariadb":
		return bool(frappe.db.has_index(table_name, index_name))

	return bool(
		frappe.db.sql(
			"""
			SELECT 1
			FROM information_schema.statistics
			WHERE table_schema = DATABASE()
			  AND table_name = %s
			  AND index_name = %s
			LIMIT 1
			""",
			(table_name, index_name),
		)
	)


def _quote_identifier(identifier):
	return f"`{identifier.replace('`', '``')}`"


def _quote_table_name(doctype):
	return _quote_identifier(get_table_name(doctype))


def verify_indexes():
	missing = []
	verified = {}

	for doctype, _, index_name in UNIQUE_INDEX_SPECS + NON_UNIQUE_INDEX_SPECS:
		exists = _index_exists(doctype, index_name)
		verified[index_name] = exists
		if not exists:
			missing.append(index_name)

	if missing:
		frappe.throw(f"Missing barcode flow indexes: {', '.join(sorted(missing))}")

	return verified
