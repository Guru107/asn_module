import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document
from frappe.utils import cint


class BarcodeFlowDefinition(Document):
	def validate(self):
		self._validate_required_child_fields()
		self._validate_unique_child_keys()
		self._validate_single_default_scope()

	def _validate_required_child_fields(self):
		for table_fieldname, key_fieldname, required_fieldname, required_label in [
			("transitions", "transition_key", "generation_mode", "Generation Mode"),
			("transitions", "transition_key", "source_node_key", "Source Node Key"),
			("transitions", "transition_key", "target_node_key", "Target Node Key"),
			("transitions", "transition_key", "action_key", "Action Key"),
			("transitions", "transition_key", "binding_mode", "Binding Mode"),
			("conditions", "condition_key", "scope", "Scope"),
			("conditions", "condition_key", "field_path", "Field Path"),
			("conditions", "condition_key", "operator", "Operator"),
			("conditions", "condition_key", "value", "Value"),
			("field_maps", "map_key", "mapping_type", "Mapping Type"),
			("field_maps", "map_key", "target_field_path", "Target Field Path"),
			("action_bindings", "binding_key", "action_key", "Action Key"),
		]:
			self._validate_required_field_in_table(
				table_fieldname=table_fieldname,
				key_fieldname=key_fieldname,
				required_fieldname=required_fieldname,
				required_label=required_label,
			)

	def _validate_required_field_in_table(
		self,
		table_fieldname: str,
		key_fieldname: str,
		required_fieldname: str,
		required_label: str,
	):
		for row in getattr(self, table_fieldname, []) or []:
			required_value = getattr(row, required_fieldname, None)
			is_missing = required_value is None or (
				isinstance(required_value, str) and not required_value.strip()
			)
			if not is_missing:
				continue

			row_key = (getattr(row, key_fieldname, None) or "").strip() or _("row {0}").format(row.idx)
			table_label = table_fieldname.replace("_", " ").title()
			frappe.throw(
				_("{0} is required for {1} in {2}.").format(required_label, row_key, table_label)
			)

	def _validate_unique_child_keys(self):
		for table_fieldname, key_fieldname, key_label in [
			("scopes", "scope_key", "Scope Key"),
			("nodes", "node_key", "Node Key"),
			("transitions", "transition_key", "Transition Key"),
			("conditions", "condition_key", "Condition Key"),
			("field_maps", "map_key", "Map Key"),
			("action_bindings", "binding_key", "Binding Key"),
		]:
			self._validate_unique_key_in_table(table_fieldname, key_fieldname, key_label)

	def _validate_unique_key_in_table(self, table_fieldname: str, key_fieldname: str, key_label: str):
		seen_keys: set[str] = set()
		duplicate_keys: set[str] = set()

		for row in getattr(self, table_fieldname, []) or []:
			key_value = (getattr(row, key_fieldname, None) or "").strip()
			if not key_value:
				continue

			if key_value in seen_keys:
				duplicate_keys.add(key_value)
				continue

			seen_keys.add(key_value)

		if duplicate_keys:
			frappe.throw(
				_("{0} must be unique within this flow. Duplicate keys: {1}").format(
					key_label,
					", ".join(sorted(duplicate_keys)),
				),
				exc=UniqueValidationError,
			)

	def _validate_single_default_scope(self):
		default_scope_count = 0
		for row in self.scopes or []:
			if cint(row.is_default):
				default_scope_count += 1

		if default_scope_count > 1:
			frappe.throw(_("Only one scope can be marked as default."))
