import frappe
from frappe.exceptions import UniqueValidationError
from frappe.tests.utils import FrappeTestCase


class TestBarcodeFlowSchema(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for doctype in [
			"barcode_flow_scope",
			"barcode_flow_node",
			"barcode_flow_transition",
			"barcode_flow_condition",
			"barcode_flow_field_map",
			"barcode_flow_action_binding",
			"barcode_flow_definition",
		]:
			frappe.reload_doc("asn_module", "doctype", doctype)

	def _new_flow(self, **overrides):
		payload = {
			"doctype": "Barcode Flow Definition",
			"flow_name": f"Flow-{frappe.generate_hash(length=8)}",
		}
		payload.update(overrides)
		return frappe.get_doc(payload)

	def _valid_scope(self, scope_key: str, **overrides):
		payload = {
			"doctype": "Barcode Flow Scope",
			"scope_key": scope_key,
			"priority": 0,
			"is_default": 0,
			"source_doctype": "ASN",
		}
		payload.update(overrides)
		return payload

	def _valid_node(self, node_key: str, label: str, **overrides):
		payload = {
			"doctype": "Barcode Flow Node",
			"node_key": node_key,
			"label": label,
			"node_type": "State",
		}
		payload.update(overrides)
		return payload

	def _valid_transition(self, transition_key: str, source_node_key: str, target_node_key: str, **overrides):
		payload = {
			"doctype": "Barcode Flow Transition",
			"transition_key": transition_key,
			"generation_mode": "runtime",
			"source_node_key": source_node_key,
			"target_node_key": target_node_key,
			"action_key": "create_purchase_receipt",
			"binding_mode": "direct",
		}
		payload.update(overrides)
		return payload

	def test_valid_definition_with_linked_rows_inserts_successfully(self):
		flow = self._new_flow(
			scopes=[self._valid_scope("default")],
			nodes=[
				self._valid_node("scan", "Scan"),
				self._valid_node("received", "Received"),
			],
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "has_warehouse",
					"scope": "items_aggregate",
					"field_path": "items.qty",
					"operator": "gt",
					"value": "0",
					"aggregate_fn": "sum",
				}
			],
			field_maps=[
				{
					"doctype": "Barcode Flow Field Map",
					"map_key": "warehouse-map",
					"mapping_type": "source",
					"source_field_path": "header.set_warehouse",
					"target_field_path": "target.set_warehouse",
				}
			],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "custom-receive",
					"trigger_event": "custom_handler",
					"action_key": "create_purchase_receipt",
					"custom_handler": "asn_module.handlers.purchase_receipt.create_from_asn",
				}
			],
			transitions=[
				self._valid_transition(
					transition_key="scan-to-received",
					source_node_key="scan",
					target_node_key="received",
					condition_key="has_warehouse",
					field_map_key="warehouse-map",
					binding_mode="custom_handler",
					binding_key="custom-receive",
				)
			],
		)

		flow.insert(ignore_permissions=True)
		self.assertTrue(flow.name)

	def test_missing_flow_name_raises_validation_error(self):
		flow = self._new_flow(flow_name=None)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_missing_required_transition_generation_mode_raises_validation_error(self):
		flow = self._new_flow(
			transitions=[
				self._valid_transition(
					transition_key="to-receiving",
					source_node_key="scan",
					target_node_key="receiving",
					generation_mode="",
				)
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_missing_required_condition_scope_raises_validation_error(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "header-company-match",
					"field_path": "header.company",
					"operator": "eq",
					"value": "TCPL",
					"scope": "",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_missing_required_field_map_mapping_type_raises_validation_error(self):
		flow = self._new_flow(
			field_maps=[
				{
					"doctype": "Barcode Flow Field Map",
					"map_key": "asn-name",
					"source_field_path": "header.name",
					"target_field_path": "target.asn_name",
					"mapping_type": "",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_duplicate_scope_key_within_flow_raises_unique_validation_error(self):
		flow = self._new_flow(
			scopes=[
				self._valid_scope("default"),
				self._valid_scope("default", source_doctype="Purchase Receipt"),
			]
		)

		with self.assertRaises(UniqueValidationError):
			flow.insert(ignore_permissions=True)

	def test_duplicate_node_key_within_flow_raises_unique_validation_error(self):
		flow = self._new_flow(
			nodes=[
				self._valid_node("scan", "Scan"),
				self._valid_node("scan", "Scan Duplicate"),
			]
		)

		with self.assertRaises(UniqueValidationError):
			flow.insert(ignore_permissions=True)

	def test_duplicate_transition_key_within_flow_raises_unique_validation_error(self):
		flow = self._new_flow(
			transitions=[
				self._valid_transition(
					transition_key="receive",
					source_node_key="scan",
					target_node_key="receiving",
				),
				self._valid_transition(
					transition_key="receive",
					source_node_key="receiving",
					target_node_key="done",
				),
			]
		)

		with self.assertRaises(UniqueValidationError):
			flow.insert(ignore_permissions=True)

	def test_transition_with_unknown_node_reference_raises_validation_error(self):
		flow = self._new_flow(
			nodes=[self._valid_node("scan", "Scan")],
			transitions=[
				self._valid_transition(
					transition_key="scan-to-received",
					source_node_key="scan",
					target_node_key="missing-node",
				)
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_field_map_constant_mapping_requires_constant_value(self):
		flow = self._new_flow(
			field_maps=[
				{
					"doctype": "Barcode Flow Field Map",
					"map_key": "constant-warehouse",
					"mapping_type": "constant",
					"target_field_path": "target.set_warehouse",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_field_map_constant_mapping_rejects_source_field_path(self):
		flow = self._new_flow(
			field_maps=[
				{
					"doctype": "Barcode Flow Field Map",
					"map_key": "constant-warehouse",
					"mapping_type": "constant",
					"source_field_path": "header.set_warehouse",
					"target_field_path": "target.set_warehouse",
					"constant_value": "WH-001",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_field_map_source_mapping_rejects_constant_value(self):
		flow = self._new_flow(
			field_maps=[
				{
					"doctype": "Barcode Flow Field Map",
					"map_key": "source-warehouse",
					"mapping_type": "source",
					"source_field_path": "header.set_warehouse",
					"target_field_path": "target.set_warehouse",
					"constant_value": "WH-001",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_action_binding_on_enter_node_requires_target_node_key(self):
		flow = self._new_flow(
			nodes=[self._valid_node("scan", "Scan")],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "enter-scan",
					"trigger_event": "On Enter Node",
					"action_key": "create_purchase_receipt",
				}
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_action_binding_on_transition_requires_known_target_transition_key(self):
		flow = self._new_flow(
			nodes=[self._valid_node("scan", "Scan")],
			transitions=[
				self._valid_transition(
					transition_key="scan-loop",
					source_node_key="scan",
					target_node_key="scan",
				)
			],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "on-transition",
					"trigger_event": "On Transition",
					"target_transition_key": "missing-transition",
					"action_key": "create_purchase_receipt",
				}
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_action_binding_on_exit_node_requires_target_node_key(self):
		flow = self._new_flow(
			nodes=[self._valid_node("scan", "Scan")],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "exit-scan",
					"trigger_event": "On Exit Node",
					"action_key": "create_purchase_receipt",
				}
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_node_trigger_rejects_transition_target_field(self):
		flow = self._new_flow(
			nodes=[self._valid_node("scan", "Scan")],
			transitions=[
				self._valid_transition(
					transition_key="scan-loop",
					source_node_key="scan",
					target_node_key="scan",
				)
			],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "enter-with-transition-target",
					"trigger_event": "On Enter Node",
					"target_node_key": "scan",
					"target_transition_key": "scan-loop",
					"action_key": "create_purchase_receipt",
				}
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_custom_handler_transition_requires_custom_handler_binding_trigger(self):
		flow = self._new_flow(
			nodes=[
				self._valid_node("scan", "Scan"),
				self._valid_node("received", "Received"),
			],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "enter-scan",
					"trigger_event": "On Enter Node",
					"target_node_key": "scan",
					"action_key": "create_purchase_receipt",
				}
			],
			transitions=[
				self._valid_transition(
					transition_key="scan-to-received",
					source_node_key="scan",
					target_node_key="received",
					binding_mode="custom_handler",
					binding_key="enter-scan",
				)
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_mapping_transition_rejects_binding_key(self):
		flow = self._new_flow(
			nodes=[
				self._valid_node("scan", "Scan"),
				self._valid_node("received", "Received"),
			],
			action_bindings=[
				{
					"doctype": "Barcode Flow Action Binding",
					"binding_key": "some-binding",
					"trigger_event": "custom_handler",
					"action_key": "create_purchase_receipt",
					"custom_handler": "asn_module.handlers.purchase_receipt.create_from_asn",
				}
			],
			transitions=[
				self._valid_transition(
					transition_key="scan-to-received",
					source_node_key="scan",
					target_node_key="received",
					binding_mode="mapping",
					binding_key="some-binding",
				)
			],
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_items_aggregate_condition_requires_aggregate_function(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "qty-total",
					"scope": "items_aggregate",
					"field_path": "items.qty",
					"operator": "gt",
					"value": "0",
					"aggregate_fn": " ",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_items_aggregate_condition_accepts_exists_aggregate_function(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "exists-aggregate",
					"scope": "items_aggregate",
					"field_path": "items.qty",
					"operator": "exists",
					"aggregate_fn": "exists",
				}
			]
		)

		flow.insert(ignore_permissions=True)
		self.assertTrue(flow.name)

	def test_items_aggregate_exists_aggregate_rejects_incompatible_operator(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "exists-aggregate",
					"scope": "items_aggregate",
					"field_path": "items.qty",
					"operator": "gt",
					"value": "0",
					"aggregate_fn": "exists",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_items_aggregate_non_exists_aggregate_rejects_operator_exists(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "sum-aggregate",
					"scope": "items_aggregate",
					"field_path": "items.qty",
					"operator": "exists",
					"aggregate_fn": "sum",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_non_aggregate_condition_rejects_aggregate_function(self):
		flow = self._new_flow(
			conditions=[
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "supplier-check",
					"scope": "header",
					"field_path": "header.supplier",
					"operator": "eq",
					"value": "SUP-0001",
					"aggregate_fn": "sum",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)
