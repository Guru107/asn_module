import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	ensure_unique_flow_key,
	normalize_key,
	validate_link_belongs_to_flow,
)


class BarcodeFlowTransition(Document):
	def autoname(self):
		self.name = build_flow_entity_name(
			flow=self.flow,
			entity_code="TRANS",
			key=self.transition_key,
			key_label="Transition Key",
		)

	def validate(self):
		self.flow = normalize_key(self.flow)
		self.transition_key = normalize_key(self.transition_key)
		self.generation_mode = normalize_key(self.generation_mode)
		self.source_node = normalize_key(self.source_node)
		self.target_node = normalize_key(self.target_node)
		self.action = normalize_key(self.action)
		self.target_doctype = normalize_key(self.target_doctype)
		self.binding_mode = normalize_key(self.binding_mode)
		self.condition = normalize_key(self.condition)
		self.field_map = normalize_key(self.field_map)
		self.action_binding = normalize_key(self.action_binding)

		if self.binding_mode == "direct":
			self.binding_mode = "mapping"

		ensure_unique_flow_key(self, key_fieldname="transition_key", key_label="Transition Key")
		for fieldname in ("source_node", "target_node", "condition", "field_map", "action_binding"):
			validate_link_belongs_to_flow(self, fieldname)
		self._validate_binding_rules()

	def _validate_binding_rules(self):
		allowed_binding_modes = {"mapping", "custom_handler", "both"}
		if self.binding_mode not in allowed_binding_modes:
			frappe.throw(
				_("Binding Mode for {0} must be one of: mapping, custom_handler, both.").format(
					self.transition_key
				)
			)

		if self.binding_mode in {"mapping", "both"} and not self.target_doctype:
			frappe.throw(
				_("Target DocType is required for {0} when binding mode is {1}.").format(
					self.transition_key,
					self.binding_mode,
				)
			)

		if self.binding_mode in {"custom_handler", "both"} and not self.action_binding:
			frappe.throw(
				_("Action Binding is required for {0} when binding mode is {1}.").format(
					self.transition_key,
					self.binding_mode,
				)
			)

		if self.binding_mode == "mapping" and self.action_binding:
			frappe.throw(
				_("Action Binding must be empty for {0} when binding mode is mapping.").format(
					self.transition_key
				)
			)

		if self.action_binding:
			binding_trigger = frappe.db.get_value(
				"Barcode Flow Action Binding", self.action_binding, "trigger_event"
			)
			binding_action = normalize_key(
				frappe.db.get_value("Barcode Flow Action Binding", self.action_binding, "action")
			)
			if binding_trigger != "custom_handler":
				frappe.throw(
					_(
						"Transition {0} requires Action Binding {1} to use trigger event custom_handler."
					).format(self.transition_key, self.action_binding)
				)
			if binding_action and binding_action != self.action:
				frappe.throw(
					_("Action Binding {0} must reference the same action as transition {1}.").format(
						self.action_binding,
						self.transition_key,
					)
				)
