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
		self._validate_transition_references()
		self._validate_mode_specific_invariants()

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

			table_label = table_fieldname.replace("_", " ").title()
			frappe.throw(
				_("{0} is required for {1} in {2}.").format(
					required_label,
					self._get_row_key(row=row, key_fieldname=key_fieldname),
					table_label,
				)
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

	def _validate_transition_references(self):
		node_keys = self._collect_key_set(self.nodes, "node_key")
		condition_keys = self._collect_key_set(self.conditions, "condition_key")
		map_keys = self._collect_key_set(self.field_maps, "map_key")
		binding_keys = self._collect_key_set(self.action_bindings, "binding_key")

		for row in self.transitions or []:
			transition_key = self._get_row_key(row=row, key_fieldname="transition_key")
			source_node_key = (row.source_node_key or "").strip()
			target_node_key = (row.target_node_key or "").strip()
			condition_key = (row.condition_key or "").strip()
			field_map_key = (getattr(row, "field_map_key", None) or "").strip()
			binding_key = (getattr(row, "binding_key", None) or "").strip()

			if source_node_key and source_node_key not in node_keys:
				frappe.throw(
					_("Transition {0} references unknown source node key: {1}").format(
						transition_key,
						source_node_key,
					)
				)

			if target_node_key and target_node_key not in node_keys:
				frappe.throw(
					_("Transition {0} references unknown target node key: {1}").format(
						transition_key,
						target_node_key,
					)
				)

			if condition_key and condition_key not in condition_keys:
				frappe.throw(
					_("Transition {0} references unknown condition key: {1}").format(
						transition_key,
						condition_key,
					)
				)

			if field_map_key and field_map_key not in map_keys:
				frappe.throw(
					_("Transition {0} references unknown field map key: {1}").format(
						transition_key,
						field_map_key,
					)
				)

			if binding_key and binding_key not in binding_keys:
				frappe.throw(
					_("Transition {0} references unknown binding key: {1}").format(
						transition_key,
						binding_key,
					)
				)

	def _validate_mode_specific_invariants(self):
		for row in self.field_maps or []:
			mapping_type = (row.mapping_type or "").strip()
			if mapping_type == "source" and not (row.source_field_path or "").strip():
				frappe.throw(
					_("Source Field Path is required for {0} when mapping type is source.").format(
						self._get_row_key(row=row, key_fieldname="map_key")
					)
				)
			if mapping_type == "constant" and not (row.constant_value or "").strip():
				frappe.throw(
					_("Constant Value is required for {0} when mapping type is constant.").format(
						self._get_row_key(row=row, key_fieldname="map_key")
					)
				)

		for row in self.action_bindings or []:
			trigger_event = (row.trigger_event or "").strip()
			if trigger_event == "custom_handler" and not (row.custom_handler or "").strip():
				frappe.throw(
					_("Custom Handler is required for {0} when trigger event is custom_handler.").format(
						self._get_row_key(row=row, key_fieldname="binding_key")
					)
				)

		for row in self.transitions or []:
			binding_mode = (row.binding_mode or "").strip()
			if binding_mode in {"custom_handler", "both"} and not (
				(getattr(row, "binding_key", None) or "").strip()
			):
				frappe.throw(
					_("Binding Key is required for {0} when binding mode is {1}.").format(
						self._get_row_key(row=row, key_fieldname="transition_key"),
						binding_mode,
					)
				)

		for row in self.conditions or []:
			operator = (row.operator or "").strip()
			value = (row.value or "").strip()
			if operator != "exists" and not value:
				frappe.throw(
					_("Value is required for {0} when operator is not exists.").format(
						self._get_row_key(row=row, key_fieldname="condition_key")
					)
				)

	def _collect_key_set(self, rows, key_fieldname: str) -> set[str]:
		return {
			(getattr(row, key_fieldname, None) or "").strip()
			for row in rows or []
			if (getattr(row, key_fieldname, None) or "").strip()
		}

	def _get_row_key(self, row, key_fieldname: str) -> str:
		return (getattr(row, key_fieldname, None) or "").strip() or _("row {0}").format(row.idx)
