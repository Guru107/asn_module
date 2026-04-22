import frappe
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
