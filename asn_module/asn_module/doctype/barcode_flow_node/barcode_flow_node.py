import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
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
		self._validate_unique_node_key()

	def _validate_unique_node_key(self):
		existing_name = frappe.db.get_value(
			"Barcode Flow Node",
			{"flow": self.flow, "node_key": self.node_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(
				_("Node Key must be unique within flow {0}. Duplicate key: {1}").format(
					self.flow, self.node_key
				),
				exc=UniqueValidationError,
			)

	def on_trash(self):
		source_transitions = frappe.get_all(
			"Barcode Flow Transition", filters={"source_node": self.name}, pluck="name"
		)
		target_transitions = frappe.get_all(
			"Barcode Flow Transition", filters={"target_node": self.name}, pluck="name"
		)
		target_bindings = frappe.get_all(
			"Barcode Flow Action Binding", filters={"target_node": self.name}, pluck="name"
		)

		blockers = []
		if source_transitions:
			blockers.append(f"Transition.source_node: {', '.join(source_transitions)}")
		if target_transitions:
			blockers.append(f"Transition.target_node: {', '.join(target_transitions)}")
		if target_bindings:
			blockers.append(f"ActionBinding.target_node: {', '.join(target_bindings)}")
		if blockers:
			frappe.throw(
				_("Cannot delete Barcode Flow Node {0}. Referenced by {1}").format(
					self.name, "; ".join(blockers)
				)
			)
