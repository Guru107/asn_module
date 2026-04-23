from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow.repository import get_active_steps_for_source
from asn_module.tests.compat import UnitTestCase


class TestRepository(UnitTestCase):
	def test_flow_step_requires_from_to_doctype(self):
		source = SimpleNamespace(doctype="ASN", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=["FLOW-1"]),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
		):
			rows = get_active_steps_for_source(source)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].from_doctype, "ASN")
		self.assertEqual(rows[0].to_doctype, "Purchase Receipt")

	def test_asn_resolves_company_from_linked_purchase_order_for_flow_scope(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-0001", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="TCPL",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)

		def _mock_get_all(doctype, *args, **kwargs):
			if doctype == "ASN Item":
				return [{"purchase_order": "PO-0001"}]
			if doctype == "Barcode Process Flow":
				return ["FLOW-1"]
			return []

		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", side_effect=_mock_get_all),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.db.get_value",
				return_value="TCPL",
			),
		):
			rows = get_active_steps_for_source(source)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].from_doctype, "ASN")
		self.assertEqual(rows[0].to_doctype, "Purchase Receipt")

	def test_asn_company_scope_mismatch_skips_flow(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-0001", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="TCPL",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)

		def _mock_get_all(doctype, *args, **kwargs):
			if doctype == "ASN Item":
				return [{"purchase_order": "PO-0001"}]
			if doctype == "Barcode Process Flow":
				return ["FLOW-1"]
			return []

		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", side_effect=_mock_get_all),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.db.get_value",
				return_value="OTHER-COMPANY",
			),
		):
			rows = get_active_steps_for_source(source)

		self.assertEqual(rows, [])
