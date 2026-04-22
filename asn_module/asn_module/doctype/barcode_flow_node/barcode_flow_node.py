from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	ensure_unique_flow_key,
	normalize_key,
)


class BarcodeFlowNode(Document):
	def autoname(self):
		self.name = build_flow_entity_name(
			flow=self.flow,
			entity_code="NODE",
			key=self.node_key,
			key_label="Node Key",
		)

	def validate(self):
		self.flow = normalize_key(self.flow)
		self.node_key = normalize_key(self.node_key)
		ensure_unique_flow_key(self, key_fieldname="node_key", key_label="Node Key")
