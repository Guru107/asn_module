from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.handlers.purchase_return import create_from_quality_inspection
from asn_module.handlers.tests.test_stock_transfer import TestCreateStockTransfer


class TestCreatePurchaseReturn(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		TestCreateStockTransfer.setUpClass()
		super().setUpClass()

	def _make_rejected_purchase_receipt_with_qi(self):
		fixture = TestCreateStockTransfer()
		pr, _accepted_qi = fixture._make_purchase_receipt_with_qi("Accepted")
		rejected_qi = fixture._make_quality_inspection(pr.name, pr.items[0].item_code, "Rejected")
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			rejected_qi.submit()
		return pr, rejected_qi

	def test_creates_return_purchase_receipt(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_purchase_return"},
		)

		self.assertEqual(result["doctype"], "Purchase Receipt")
		return_pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(return_pr.docstatus, 0)
		self.assertEqual(return_pr.is_return, 1)
		self.assertEqual(return_pr.return_against, pr.name)
		self.assertTrue(return_pr.items[0].qty < 0)
		self.assertEqual(return_pr.items[0].purchase_receipt_item, pr.items[0].name)

	def test_rejects_non_rejected_qi(self):
		fixture = TestCreateStockTransfer()
		_pr, qi = fixture._make_purchase_receipt_with_qi("Accepted")

		with self.assertRaises(frappe.ValidationError):
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)

	def test_rejects_before_pr_submit(self):
		fixture = TestCreateStockTransfer()
		pr, _accepted_qi = fixture._make_purchase_receipt_with_qi(
			"Accepted",
			submit_purchase_receipt=False,
		)
		qi = fixture._make_quality_inspection(pr.name, pr.items[0].item_code, "Rejected")
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			qi.submit()

		with self.assertRaises(frappe.ValidationError):
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)
