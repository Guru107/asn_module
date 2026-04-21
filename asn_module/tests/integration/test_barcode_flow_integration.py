from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.barcode_flow.runtime import execute_transition_binding


class TestBarcodeFlowIntegration(FrappeTestCase):
	def test_execute_transition_binding_returns_child_scan_codes_for_hybrid_and_immediate(self):
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=SimpleNamespace(custom_handler="asn_module.tests.integration.fake_handler"),
			target_node_key="received",
		)
		flow_definition = SimpleNamespace(
			transitions=[
				SimpleNamespace(
					transition_key="child-hybrid",
					source_node_key="received",
					action_key="create_purchase_invoice",
					generation_mode="hybrid",
				),
				SimpleNamespace(
					transition_key="child-immediate",
					source_node_key="received",
					action_key="confirm_putaway",
					generation_mode="immediate",
				),
				SimpleNamespace(
					transition_key="child-runtime",
					source_node_key="received",
					action_key="create_stock_transfer",
					generation_mode="runtime",
				),
			]
		)
		source_doc = {"doctype": "DocType", "name": "QR Action Registry"}
		target_name = f"BFI-{frappe.generate_hash(length=8)}"

		def handler(**_kwargs):
			return {
				"doctype": "DocType",
				"name": target_name,
				"url": f"/app/doctype/{target_name}",
			}

		with patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler):
			result = execute_transition_binding(
				transition=transition,
				source_doc=source_doc,
				flow_definition=flow_definition,
			)

		self.assertEqual(result["doctype"], "DocType")
		self.assertEqual(result["name"], target_name)
		self.assertEqual(result["url"], f"/app/doctype/{target_name}")

		generated = result["generated_scan_codes"]
		self.assertEqual(len(generated), 2)
		self.assertEqual({row["action_key"] for row in generated}, {"create_purchase_invoice", "confirm_putaway"})
		self.assertNotIn("create_stock_transfer", {row["action_key"] for row in generated})
		self.assertEqual(
			{row["generation_mode"] for row in generated},
			{"hybrid", "immediate"},
		)
		for row in generated:
			self.assertTrue(row["scan_code"])
			self.assertTrue(row["human_readable"])

		for action_key in ("create_purchase_invoice", "confirm_putaway"):
			self.assertTrue(
				frappe.db.exists(
					"Scan Code",
					{
						"action_key": action_key,
						"source_doctype": "DocType",
						"source_name": target_name,
						"status": "Active",
					},
				)
			)

		self.assertFalse(
			frappe.db.exists(
				"Scan Code",
				{
					"action_key": "create_stock_transfer",
					"source_doctype": "DocType",
					"source_name": target_name,
					"status": "Active",
				},
			)
		)
