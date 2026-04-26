from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.barcode_process_flow import runtime
from asn_module.setup_actions import DEFAULT_STANDARD_FLOW_NAME, ensure_default_standard_handler_flow
from asn_module.utils import cypress_helpers


class TestDefaultStandardHandlersIntegration(FrappeTestCase):
	def test_purchase_material_request_submit_generates_scan_codes_from_default_flow(self):
		ensure_default_standard_handler_flow()
		cypress_helpers._deactivate_previous_e2e_standard_handler_flows()
		for row in frappe.get_all(
			"Barcode Process Flow",
			filters={"is_active": 1},
			fields=["name"],
		):
			name = (row.get("name") or "").strip()
			if not name or name == DEFAULT_STANDARD_FLOW_NAME:
				continue
			frappe.db.set_value("Barcode Process Flow", name, "is_active", 0, update_modified=False)

		run_id = "INTG" + frappe.generate_hash(length=6)
		source_docs = cypress_helpers._prepare_standard_handler_source_docs(
			run_id=run_id,
			template_keys={"mr_purchase_to_po"},
		)
		mr_name = source_docs["mr_purchase_to_po"]["name"]

		flow_name = frappe.db.get_value(
			"Barcode Process Flow",
			DEFAULT_STANDARD_FLOW_NAME,
			"name",
		)
		self.assertEqual(flow_name, DEFAULT_STANDARD_FLOW_NAME)
		mr_doc = frappe.get_doc("Material Request", mr_name)

		with (
			patch(
				"asn_module.qr_engine.generate.generate_qr",
				return_value={
					"scan_code": "ABCD1234EFGH5678",
					"human_readable": "ABCD1234EFGH5678",
					"image_base64": "ZmFrZQ==",
				},
			),
			patch(
				"asn_module.qr_engine.generate.generate_barcode",
				return_value={
					"scan_code": "ABCD1234EFGH5678",
					"human_readable": "ABCD1234EFGH5678",
					"image_base64": "ZmFrZQ==",
				},
			),
			patch(
				"asn_module.barcode_process_flow.runtime._attach_followup_image",
				return_value="/files/fake.png",
			),
		):
			generated = runtime.generate_codes_for_source_doc(
				source_doc=mr_doc,
				conditioned_only=False,
			)

		self.assertTrue(generated)
		action_keys = {(row.get("action_key") or "").strip() for row in generated}
		self.assertIn("mr_purchase_to_po", action_keys)
