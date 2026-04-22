import frappe
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
