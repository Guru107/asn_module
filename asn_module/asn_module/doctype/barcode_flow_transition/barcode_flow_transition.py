import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document
from frappe.utils import cint

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

		self._validate_unique_transition_key()
		self._validate_same_flow_links()
		self._validate_binding_mode_contract()

	def _validate_unique_transition_key(self):
		existing_name = frappe.db.get_value(
			"Barcode Flow Transition",
			{"flow": self.flow, "transition_key": self.transition_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(
				_("Transition Key must be unique within flow {0}. Duplicate key: {1}").format(
					self.flow, self.transition_key
				),
				exc=UniqueValidationError,
			)

	def _validate_same_flow_links(self):
		self._validate_link_flow("Barcode Flow Node", self.source_node, "Source Node")
		self._validate_link_flow("Barcode Flow Node", self.target_node, "Target Node")
		self._validate_link_flow("Barcode Flow Condition", self.condition, "Condition")
		self._validate_link_flow("Barcode Flow Field Map", self.field_map, "Field Map")
		self._validate_link_flow("Barcode Flow Action Binding", self.action_binding, "Action Binding")

	def _validate_link_flow(self, doctype: str, docname: str, label: str):
		if not docname:
			return

		link_flow = frappe.db.get_value(doctype, docname, "flow")
		if link_flow and normalize_key(link_flow) != self.flow:
			frappe.throw(_("{0} must belong to flow {1}.").format(label, self.flow))

	def _validate_binding_mode_contract(self):
		binding = self._get_action_binding_contract() if self.action_binding else None
		override_wins = cint(binding.handler_override_wins) if binding else 0

		if self.binding_mode in {"mapping", "both"}:
			if not self.field_map:
				frappe.throw(_("Field Map is required when Binding Mode is {0}.").format(self.binding_mode))
			if self.binding_mode == "mapping" and not self.target_doctype:
				frappe.throw(_("Target DocType is required when Binding Mode is {0}.").format(self.binding_mode))
			if self.binding_mode == "both" and not override_wins and not self.target_doctype:
				frappe.throw(_("Target DocType is required when Binding Mode is both unless handler override wins."))

		if self.binding_mode not in {"custom_handler", "both"}:
			return

		if not self.action_binding:
			frappe.throw(_("Action Binding is required when Binding Mode is {0}.").format(self.binding_mode))

		if not binding:
			return

		if binding.trigger_event != "custom_handler":
			frappe.throw(_("Action Binding must use the custom_handler trigger event."))
		if not normalize_key(binding.custom_handler):
			frappe.throw(_("Action Binding must define a Custom Handler for handler binding modes."))

	def _get_action_binding_contract(self):
		return frappe.db.get_value(
			"Barcode Flow Action Binding",
			self.action_binding,
			["trigger_event", "custom_handler", "handler_override_wins"],
			as_dict=True,
		)
