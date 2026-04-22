import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	normalize_key,
)


class BarcodeFlowActionBinding(Document):
	def autoname(self):
		self.name = build_flow_entity_name(
			flow=self.flow,
			entity_code="BIND",
			key=self.binding_key,
			key_label="Binding Key",
		)

	def validate(self):
		self.flow = normalize_key(self.flow)
		self.binding_key = normalize_key(self.binding_key)
		self.trigger_event = normalize_key(self.trigger_event)
		self.target_node = normalize_key(self.target_node)
		self.target_transition = normalize_key(self.target_transition)
		self.action = normalize_key(self.action)
		self.custom_handler = normalize_key(self.custom_handler)

		self._validate_trigger_contract()

	def _validate_trigger_contract(self):
		if self.trigger_event == "custom_handler":
			if not self.custom_handler:
				frappe.throw(_("Custom Handler is required when Trigger Event is custom_handler."))
			if self.target_node or self.target_transition:
				frappe.throw(_("Target Node and Target Transition must be empty when Trigger Event is custom_handler."))
			return

		if self.trigger_event in {"On Enter Node", "On Exit Node"} and not self.target_node:
			frappe.throw(_("Target Node is required when Trigger Event is {0}.").format(self.trigger_event))

		if self.trigger_event == "On Transition" and not self.target_transition:
			frappe.throw(_("Target Transition is required when Trigger Event is On Transition."))
