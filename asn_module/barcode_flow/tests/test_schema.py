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

	def test_missing_flow_name_raises_validation_error(self):
		flow = self._new_flow(flow_name=None)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_missing_required_transition_field_raises_validation_error(self):
		flow = self._new_flow(
			transitions=[
				{
					"doctype": "Barcode Flow Transition",
					"transition_key": "to-receiving",
					"from_node_key": "scan",
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			flow.insert(ignore_permissions=True)

	def test_duplicate_transition_key_within_flow_raises_unique_validation_error(self):
		flow = self._new_flow(
			transitions=[
				{
					"doctype": "Barcode Flow Transition",
					"transition_key": "receive",
					"from_node_key": "scan",
					"to_node_key": "receiving",
				},
				{
					"doctype": "Barcode Flow Transition",
					"transition_key": "receive",
					"from_node_key": "receiving",
					"to_node_key": "done",
				},
			]
		)

		with self.assertRaises(UniqueValidationError):
			flow.insert(ignore_permissions=True)
