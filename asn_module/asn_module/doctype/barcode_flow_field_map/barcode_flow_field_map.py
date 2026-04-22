import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	normalize_key,
)


class BarcodeFlowFieldMap(Document):
	def autoname(self):
		self.name = build_flow_entity_name(
			flow=self.flow,
			entity_code="MAP",
			key=self.map_key,
			key_label="Map Key",
		)

	def validate(self):
		self.flow = normalize_key(self.flow)
		self.map_key = normalize_key(self.map_key)
		self.mapping_type = normalize_key(self.mapping_type)
		self.source_field_path = normalize_key(self.source_field_path)
		self.target_field_path = normalize_key(self.target_field_path)
		self.constant_value = (self.constant_value or "").strip()
		self.transform_key = normalize_key(self.transform_key)
		self._validate_unique_map_key()

	def _validate_unique_map_key(self):
		existing_name = frappe.db.get_value(
			"Barcode Flow Field Map",
			{"flow": self.flow, "map_key": self.map_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(
				_("Map Key must be unique within flow {0}. Duplicate key: {1}").format(
					self.flow, self.map_key
				),
				exc=UniqueValidationError,
			)
