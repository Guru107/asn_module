from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.handlers.purchase_return import create_from_quality_inspection
from asn_module.handlers.tests.test_stock_transfer import TestCreateStockTransfer


class TestPurchaseReturnErrors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		TestCreateStockTransfer.setUpClass()
		if not frappe.db.has_column("Quality Inspection", "purchase_receipt_item"):
			frappe.db.sql(
				"ALTER TABLE `tabQuality Inspection` ADD COLUMN `purchase_receipt_item` VARCHAR(255)"
			)
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

	def test_qi_item_found_in_pr_returns_that_item(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()
		frappe.set_user("Administrator")
		qi.purchase_receipt_item = pr.items[0].name
		qi.save(ignore_permissions=True)

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
		self.assertEqual(return_pr.items[0].purchase_receipt_item, pr.items[0].name)

	def test_qi_item_not_found_in_pr_raises(self):
		pr, qi = self._make_rejected_purchase_receipt_with_qi()
		frappe.set_user("Administrator")
		frappe.db.set_value("Quality Inspection", qi.name, "purchase_receipt_item", "NONEXISTENT-ROW")
		frappe.db.set_value("Quality Inspection", qi.name, "item_code", "NONEXISTENT-ITEM")

		with self.assertRaises(frappe.ValidationError) as context:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_purchase_return"},
			)

		self.assertIn("not found", str(context.exception))

	def test_ambiguous_qi_raises_validation_error(self):
		fixture = TestCreateStockTransfer()
		original_setting = frappe.db.get_single_value(
			"Stock Settings", "allow_to_make_quality_inspection_after_purchase_or_delivery"
		)
		frappe.db.set_value(
			"Stock Settings",
			"Stock Settings",
			"allow_to_make_quality_inspection_after_purchase_or_delivery",
			1,
		)
		try:
			item_code = "_Test ASN Item No Inspect"
			if not frappe.db.exists("Item", item_code):
				item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
				uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": item_code,
						"item_name": item_code,
						"item_group": item_group,
						"stock_uom": uom,
					}
				).insert(ignore_permissions=True)
			purchase_order = create_purchase_order(
				transaction_date="2026-03-30",
				schedule_date="2026-03-31",
				item_schedule_date="2026-03-31",
				item_code=item_code,
				qty=10,
			)
			company = purchase_order.company
			destination_warehouse = fixture._ensure_destination_warehouse(company)
			fixture._ensure_item_default(item_code, company, destination_warehouse)

			pr = frappe.get_doc(
				{
					"doctype": "Purchase Receipt",
					"supplier": purchase_order.supplier,
					"company": company,
					"items": [
						{
							"item_code": item_code,
							"qty": 5,
							"rate": purchase_order.items[0].rate,
							"purchase_order": purchase_order.name,
							"purchase_order_item": purchase_order.items[0].name,
							"warehouse": purchase_order.items[0].warehouse,
						},
						{
							"item_code": item_code,
							"qty": 5,
							"rate": purchase_order.items[0].rate,
							"purchase_order": purchase_order.name,
							"purchase_order_item": purchase_order.items[0].name,
							"warehouse": purchase_order.items[0].warehouse,
						},
					],
				}
			)
			pr.insert(ignore_permissions=True)

			qi = fixture._make_quality_inspection(pr.name, item_code, "Rejected")
			with (
				patch(
					"asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}
				),
				patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
				patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
			):
				qi.submit()

			pr.reload()
			pr.items[0].quality_inspection = qi.name
			pr.items[1].quality_inspection = qi.name
			pr.save(ignore_permissions=True)
			pr.submit()

			with self.assertRaises(frappe.ValidationError) as context:
				create_from_quality_inspection(
					source_doctype="Quality Inspection",
					source_name=qi.name,
					payload={"action": "create_purchase_return"},
				)

			self.assertIn("Multiple", str(context.exception))
		finally:
			frappe.db.set_value(
				"Stock Settings",
				"Stock Settings",
				"allow_to_make_quality_inspection_after_purchase_or_delivery",
				original_setting,
			)
