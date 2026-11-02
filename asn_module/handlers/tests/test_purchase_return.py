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
		return fixture._make_rejected_purchase_receipt_with_qi()

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

	def _require_taxes_on_receipts(self):
		"""Make ``taxes`` mandatory the way a production Property Setter does, on any site."""
		patcher = patch.object(frappe.get_meta("Purchase Receipt").get_field("taxes"), "reqd", 1)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _set_purchase_order_taxes(self, purchase_order, company, rows):
		account = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Tax", "is_group": 0},
			"name",
			order_by="name asc",
		) or (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": "ASN Return Test Tax",
					"company": company,
					"account_type": "Tax",
					"parent_account": frappe.db.get_value(
						"Account",
						{"company": company, "root_type": "Liability", "is_group": 1},
						"name",
						order_by="lft asc",
					),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.delete(
			"Purchase Taxes and Charges", {"parent": purchase_order, "parenttype": "Purchase Order"}
		)
		for idx, row in enumerate(rows, start=1):
			frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges",
					"parent": purchase_order,
					"parenttype": "Purchase Order",
					"parentfield": "taxes",
					"idx": idx,
					"category": "Total",
					"add_deduct_tax": "Add",
					"account_head": account,
					"description": f"Return test tax {idx}",
					**row,
				}
			).db_insert()

	def test_return_copies_purchase_order_taxes_when_site_requires_them(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()
		row = pr.items[0]
		self._set_purchase_order_taxes(
			row.purchase_order,
			pr.company,
			[
				{"charge_type": "On Net Total", "rate": 18, "included_in_print_rate": 1},
				{
					"charge_type": "On Previous Row Amount",
					"row_id": "1",
					"rate": 10,
					"included_in_print_rate": 1,
				},
				{"charge_type": "Actual", "tax_amount": 100},
			],
		)
		# As a real PO with inclusive tax stores it: net_total is below the item amounts.
		frappe.db.set_value(
			"Purchase Order", row.purchase_order, "net_total", 10 * row.rate / 1.18, update_modified=False
		)
		self._require_taxes_on_receipts()

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_purchase_return"},
		)

		return_pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(
			[
				(tax.charge_type, tax.row_id or None, tax.included_in_print_rate, tax.rate)
				for tax in return_pr.taxes
			],
			[
				("On Net Total", None, 1, 18),
				("On Previous Row Amount", "1", 1, 10),
				("Actual", None, 0, 0),
			],
		)
		# Sample of 4 from a PO of 10: the return carries -4/10 of the PO's flat charge.
		self.assertAlmostEqual(return_pr.taxes[2].tax_amount, -40, places=2)
		self.assertLess(return_pr.grand_total, 0)

	def test_return_names_the_purchase_order_when_it_has_no_taxes_to_copy(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()
		self._set_purchase_order_taxes(pr.items[0].purchase_order, pr.company, [])
		self._require_taxes_on_receipts()

		with self.assertRaises(frappe.ValidationError) as context:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)

		self.assertIn(pr.items[0].purchase_order, str(context.exception))

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
		_pr, qi = fixture._make_purchase_receipt_with_qi(
			"Rejected",
			submit_purchase_receipt=False,
		)

		with self.assertRaises(frappe.ValidationError):
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)

	def test_rejects_cancelled_quality_inspection(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()
		frappe.db.set_value("Quality Inspection", qi.name, "docstatus", 2, update_modified=False)
		qi.reload()

		with self.assertRaises(frappe.ValidationError):
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)

		self.assertEqual(pr.docstatus, 1)
