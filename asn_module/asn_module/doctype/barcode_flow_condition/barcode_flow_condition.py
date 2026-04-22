import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	normalize_key,
)


class BarcodeFlowCondition(Document):
	def autoname(self):
		self.name = build_flow_entity_name(
			flow=self.flow,
			entity_code="COND",
			key=self.condition_key,
			key_label="Condition Key",
		)

	def validate(self):
		self.flow = normalize_key(self.flow)
		self.condition_key = normalize_key(self.condition_key)
		self.scope = normalize_key(self.scope)
		self.field_path = normalize_key(self.field_path)
		self.operator = normalize_key(self.operator)
		self.value = (self.value or "").strip()
		self.aggregate_fn = normalize_key(self.aggregate_fn)
