import frappe
from frappe import _
from frappe.model.document import Document

from asn_module.asn_module.doctype.barcode_flow_definition.barcode_flow_definition import (
	build_flow_entity_name,
	ensure_unique_flow_key,
	normalize_key,
	validate_link_belongs_to_flow,
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

		ensure_unique_flow_key(self, key_fieldname="binding_key", key_label="Binding Key")
		validate_link_belongs_to_flow(self, "target_node")
		validate_link_belongs_to_flow(self, "target_transition")
		self._validate_trigger_rules()

	def _validate_trigger_rules(self):
		if self.trigger_event in {"On Enter Node", "On Exit Node"}:
			if not self.target_node:
				frappe.throw(
					_("Target Node is required for {0} when trigger event is {1}.").format(
						self.binding_key,
						self.trigger_event,
					)
				)
			if self.target_transition:
				frappe.throw(
					_("Target Transition must be empty for {0} when trigger event is {1}.").format(
						self.binding_key,
						self.trigger_event,
					)
				)
			if self.custom_handler:
				frappe.throw(
					_("Custom Handler must be empty for {0} when trigger event is {1}.").format(
						self.binding_key,
						self.trigger_event,
					)
				)
			return

		if self.trigger_event == "On Transition":
			if not self.target_transition:
				frappe.throw(
					_("Target Transition is required for {0} when trigger event is On Transition.").format(
						self.binding_key
					)
				)
			if self.target_node:
				frappe.throw(
					_("Target Node must be empty for {0} when trigger event is On Transition.").format(
						self.binding_key
					)
				)
			if self.custom_handler:
				frappe.throw(
					_("Custom Handler must be empty for {0} when trigger event is On Transition.").format(
						self.binding_key
					)
				)
			return

		if self.trigger_event == "custom_handler":
			if not self.custom_handler:
				frappe.throw(
					_("Custom Handler is required for {0} when trigger event is custom_handler.").format(
						self.binding_key
					)
				)
			if self.target_node or self.target_transition:
				frappe.throw(
					_(
						"Target Node and Target Transition must be empty for {0} when trigger event is custom_handler."
					).format(self.binding_key)
				)
