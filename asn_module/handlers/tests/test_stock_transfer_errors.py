from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.handlers.stock_transfer import create_from_quality_inspection
from asn_module.handlers.tests.date_utils import fiscal_year_test_dates
from asn_module.handlers.tests.qi_schema import ensure_quality_inspection_purchase_receipt_item_column


class TestStockTransferErrors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		ensure_quality_inspection_purchase_receipt_item_column()
		super().setUpClass()

	def _ensure_item(self):
		item_code = "_Test ASN Item"
		if frappe.db.exists("Item", item_code):
			frappe.db.set_value("Item", item_code, "inspection_required_before_purchase", 1)
			return item_code

		item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
		uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": uom,
				"inspection_required_before_purchase": 1,
			}
		).insert(ignore_permissions=True)
		return item_code

	def _ensure_destination_warehouse(self, company):
		warehouse_name = "_Test Accepted Warehouse"
		existing_name = frappe.db.get_value(
			"Warehouse",
			{"warehouse_name": warehouse_name, "company": company},
			"name",
		)
		if existing_name:
			return existing_name

		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": company,
			}
		).insert(ignore_permissions=True)
		return warehouse.name

	def _ensure_item_default(self, item_code, company, warehouse):
		item = frappe.get_doc("Item", item_code)
		for row in item.item_defaults:
			if row.company == company:
				row.default_warehouse = warehouse
				item.save(ignore_permissions=True)
				return

		item.append(
			"item_defaults",
			{
				"company": company,
				"default_warehouse": warehouse,
			},
		)
		item.save(ignore_permissions=True)

	def _make_purchase_receipt_with_qi(
		self,
		qi_status,
		submit_quality_inspection=True,
		submit_purchase_receipt=True,
	):
		item_code = self._ensure_item()
		dates = fiscal_year_test_dates()
		purchase_order = create_purchase_order(
			transaction_date=dates["transaction_date"],
			schedule_date=dates["schedule_date"],
			item_schedule_date=dates["item_schedule_date"],
			item_code=item_code,
			qty=10,
		)
		company = purchase_order.company
		destination_warehouse = self._ensure_destination_warehouse(company)
		self._ensure_item_default(item_code, company, destination_warehouse)

		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": purchase_order.supplier,
				"company": company,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": purchase_order.items[0].rate,
						"purchase_order": purchase_order.name,
						"purchase_order_item": purchase_order.items[0].name,
						"warehouse": purchase_order.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		qi = self._make_quality_inspection(pr.name, item_code, qi_status)
		if submit_quality_inspection:
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
		pr.save(ignore_permissions=True)
		if submit_purchase_receipt:
			pr.submit()
		return pr, qi

	def _make_quality_inspection(self, purchase_receipt_name, item_code, status):
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": purchase_receipt_name,
				"item_code": item_code,
				"sample_size": 4,
				"status": status,
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
			}
		)
		qi.insert(ignore_permissions=True)
		return qi

	def test_qi_item_found_in_pr_returns_that_item(self):
		pr, qi = self._make_purchase_receipt_with_qi("Accepted")
		pr.reload()

		frappe.db.set_value("Quality Inspection", qi.name, "purchase_receipt_item", pr.items[0].name)
		qi.reload()

		frappe.set_user("Administrator")
		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_stock_transfer"},
		)

		self.assertEqual(result["doctype"], "Stock Entry")
		se = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(se.docstatus, 0)
		self.assertEqual(se.stock_entry_type, "Material Transfer")
		self.assertEqual(se.items[0].item_code, qi.item_code)
		self.assertEqual(se.items[0].s_warehouse, pr.items[0].warehouse)

	def test_qi_item_not_found_in_pr_raises(self):
		item_code = self._ensure_item()
		dates = fiscal_year_test_dates()
		purchase_order = create_purchase_order(
			transaction_date=dates["transaction_date"],
			schedule_date=dates["schedule_date"],
			item_schedule_date=dates["item_schedule_date"],
			item_code=item_code,
			qty=10,
		)
		company = purchase_order.company
		destination_warehouse = self._ensure_destination_warehouse(company)
		self._ensure_item_default(item_code, company, destination_warehouse)

		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": purchase_order.supplier,
				"company": company,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": purchase_order.items[0].rate,
						"purchase_order": purchase_order.name,
						"purchase_order_item": purchase_order.items[0].name,
						"warehouse": purchase_order.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)

		qi = self._make_quality_inspection(pr.name, item_code, "Accepted")
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			qi.submit()

		pr.reload()
		pr.items[0].quality_inspection = qi.name
		pr.save(ignore_permissions=True)
		pr.submit()
		pr.reload()

		frappe.db.set_value("Quality Inspection", qi.name, "purchase_receipt_item", "FAKE-ROW-ID")
		frappe.db.set_value("Quality Inspection", qi.name, "item_code", "NONEXISTENT-ITEM-XYZ")
		qi.reload()

		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError) as cm:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_stock_transfer"},
			)

		self.assertIn("not found", str(cm.exception).lower())
