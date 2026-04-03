from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	before_tests,
	create_purchase_order,
	make_test_asn,
)
from asn_module.handlers.purchase_invoice import create_from_purchase_receipt


class TestCreatePurchaseInvoice(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_submitted_purchase_receipt(self, *, asn=None, per_billed=0):
		purchase_order = create_purchase_order(
			transaction_date="2026-03-30",
			schedule_date="2026-03-31",
			item_schedule_date="2026-03-31",
		)
		if asn is None:
			asn = make_test_asn(purchase_order=purchase_order)
			asn.insert(ignore_permissions=True)
			with _mock_asn_attachments():
				asn.submit()

		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": purchase_order.supplier,
				"company": purchase_order.company,
				"asn": asn.name,
				"items": [
					{
						"item_code": purchase_order.items[0].item_code,
						"qty": 2,
						"rate": purchase_order.items[0].rate,
						"purchase_order": purchase_order.name,
						"purchase_order_item": purchase_order.items[0].name,
						"warehouse": purchase_order.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		if per_billed:
			frappe.db.set_value("Purchase Receipt", pr.name, "per_billed", per_billed, update_modified=False)
			pr.reload()
		with (
			_mock_asn_attachments(),
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.purchase_receipt._attach_qr_to_doc"),
		):
			pr.submit()
		return pr

	def test_creates_draft_purchase_invoice_from_purchase_receipt(self):
		asn = make_test_asn(supplier_invoice_no="INV-0001")
		asn.insert(ignore_permissions=True)
		with (
			_mock_asn_attachments(),
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.purchase_receipt._attach_qr_to_doc"),
		):
			asn.submit()
		pr = self._make_submitted_purchase_receipt(asn=asn)

		result = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)

		self.assertEqual(result["doctype"], "Purchase Invoice")
		pi = frappe.get_doc("Purchase Invoice", result["name"])
		self.assertEqual(pi.docstatus, 0)
		self.assertEqual(pi.supplier, pr.supplier)
		self.assertEqual(pi.bill_no, asn.supplier_invoice_no)
		self.assertEqual(pi.bill_date, asn.supplier_invoice_date)
		self.assertEqual(pi.asn, pr.asn)
		self.assertEqual(len(pi.items), len(pr.items))
		self.assertEqual(pi.items[0].purchase_receipt, pr.name)
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertEqual(pi.items[0].purchase_order, pr.items[0].purchase_order)
		self.assertEqual(pi.items[0].po_detail, pr.items[0].purchase_order_item)

	def test_returns_existing_draft_purchase_invoice_for_same_purchase_receipt(self):
		pr = self._make_submitted_purchase_receipt()

		first = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)
		second = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)

		self.assertEqual(first["name"], second["name"])
		self.assertEqual(
			frappe.db.count("Purchase Invoice Item", {"purchase_receipt": pr.name, "docstatus": 0}),
			1,
		)

	def test_rejects_unsubmitted_purchase_receipt(self):
		pr = self._make_submitted_purchase_receipt()
		frappe.db.set_value("Purchase Receipt", pr.name, "docstatus", 0, update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			create_from_purchase_receipt(
				source_doctype="Purchase Receipt",
				source_name=pr.name,
				payload={"action": "create_purchase_invoice"},
			)

	def test_rejects_fully_billed_purchase_receipt(self):
		pr = self._make_submitted_purchase_receipt(per_billed=100)

		with self.assertRaises(frappe.ValidationError):
			create_from_purchase_receipt(
				source_doctype="Purchase Receipt",
				source_name=pr.name,
				payload={"action": "create_purchase_invoice"},
			)
