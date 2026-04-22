import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
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

		self._validate_unique_binding_key()
		self._validate_same_flow_links()
		self._validate_trigger_contract()

	def _validate_unique_binding_key(self):
		existing_name = frappe.db.get_value(
			"Barcode Flow Action Binding",
			{"flow": self.flow, "binding_key": self.binding_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(
				_("Binding Key must be unique within flow {0}. Duplicate key: {1}").format(
					self.flow, self.binding_key
				),
				exc=UniqueValidationError,
			)

	def _validate_same_flow_links(self):
		self._validate_link_flow("Barcode Flow Node", self.target_node, "Target Node")
		self._validate_link_flow("Barcode Flow Transition", self.target_transition, "Target Transition")

	def _validate_link_flow(self, doctype: str, docname: str, label: str):
		if not docname:
			return

		link_flow = frappe.db.get_value(doctype, docname, "flow")
		if link_flow and normalize_key(link_flow) != self.flow:
			frappe.throw(_("{0} must belong to flow {1}.").format(label, self.flow))

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
