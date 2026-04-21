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
