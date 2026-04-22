import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	ensure_unique_flow_key,
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

		ensure_unique_flow_key(self, key_fieldname="condition_key", key_label="Condition Key")
		self._validate_scope_specific_rules()

	def _validate_scope_specific_rules(self):
		if self.scope == "items_aggregate" and not self.aggregate_fn:
			frappe.throw(
				_("Aggregate Function is required for {0} when scope is items_aggregate.").format(
					self.condition_key
				)
			)

		if self.scope != "items_aggregate" and self.aggregate_fn:
			frappe.throw(
				_("Aggregate Function must be empty for {0} when scope is not items_aggregate.").format(
					self.condition_key
				)
			)

		if self.scope == "items_aggregate" and self.aggregate_fn == "exists":
			if self.operator not in {"=", "!=", "is_set", "exists"}:
				frappe.throw(
					_(
						"Operator must be one of =, !=, is_set, exists for {0} when aggregate function is exists."
					).format(self.condition_key)
				)

		if self.scope == "items_aggregate" and self.aggregate_fn != "exists" and self.operator == "exists":
			frappe.throw(
				_("Operator exists is only allowed for {0} when aggregate function is exists.").format(
					self.condition_key
				)
			)

		if self.operator not in {"exists", "is_set"} and not self.value:
			frappe.throw(
				_("Value is required for {0} unless operator is exists or is_set.").format(
					self.condition_key
				)
			)
