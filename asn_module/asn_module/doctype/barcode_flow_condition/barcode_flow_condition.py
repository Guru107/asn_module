import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
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
		self._validate_unique_condition_key()

	def _validate_unique_condition_key(self):
		existing_name = frappe.db.get_value(
			"Barcode Flow Condition",
			{"flow": self.flow, "condition_key": self.condition_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(
				_("Condition Key must be unique within flow {0}. Duplicate key: {1}").format(
					self.flow, self.condition_key
				),
				exc=UniqueValidationError,
			)
