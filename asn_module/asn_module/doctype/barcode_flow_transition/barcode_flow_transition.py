import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	normalize_key,
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

		self._validate_binding_mode_contract()

	def _validate_binding_mode_contract(self):
		if self.binding_mode in {"mapping", "both"}:
			if not self.field_map:
				frappe.throw(_("Field Map is required when Binding Mode is {0}.").format(self.binding_mode))
			if not self.target_doctype:
				frappe.throw(_("Target DocType is required when Binding Mode is {0}.").format(self.binding_mode))

		if self.binding_mode not in {"custom_handler", "both"}:
			return

		if not self.action_binding:
			frappe.throw(_("Action Binding is required when Binding Mode is {0}.").format(self.binding_mode))

		binding = frappe.db.get_value(
			"Barcode Flow Action Binding",
			self.action_binding,
			["trigger_event", "custom_handler"],
			as_dict=True,
		)
		if not binding:
			return

		if binding.trigger_event != "custom_handler":
			frappe.throw(_("Action Binding must use the custom_handler trigger event."))
		if not normalize_key(binding.custom_handler):
			frappe.throw(_("Action Binding must define a Custom Handler for handler binding modes."))
