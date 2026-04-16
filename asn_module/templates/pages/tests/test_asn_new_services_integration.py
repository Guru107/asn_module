from dataclasses import dataclass

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
from asn_module.templates.pages.asn_new_services import (
	INVOICE_GROUP_FIELDS,
	ParsedBulkRow,
	PortalValidationError,
	fetch_purchase_order_items,
	validate_invoice_group_consistency,
	validate_no_duplicate_po_sr_no,
	validate_qty_within_remaining,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates
from asn_module.utils.test_setup import before_tests


def _test_dates():
	return get_fiscal_year_test_dates()


class TestAsnNewServicesIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def test_fetch_purchase_order_items_empty_list_returns_empty(self):
		rows_by_key, remaining_qty_by_name = fetch_purchase_order_items([])
		self.assertEqual(rows_by_key, {})
		self.assertEqual(remaining_qty_by_name, {})

	def test_fetch_purchase_order_items_returns_grouped_rows_and_remaining_qty(self):
		po = create_purchase_order(qty=10, rate=100)
		try:
			rows_by_key, remaining_qty_by_name = fetch_purchase_order_items([po.name])

			self.assertIsInstance(rows_by_key, dict)
			self.assertIsInstance(remaining_qty_by_name, dict)

			self.assertGreater(len(rows_by_key), 0)

			for key, rows in rows_by_key.items():
				self.assertIsInstance(key, tuple)
				self.assertEqual(len(key), 2)
				self.assertIsInstance(rows, list)
				for row in rows:
					self.assertEqual(row.parent, po.name)

			for _poi_name, remaining in remaining_qty_by_name.items():
				self.assertIsInstance(remaining, float)
				self.assertGreaterEqual(remaining, 0)

		finally:
			if po.docstatus == 1:
				po.cancel()
			po.delete()

	def test_fetch_purchase_order_items_handles_100_line_purchase_order(self):
		po = create_purchase_order(qty=1, rate=100, item_count=100)
		try:
			rows_by_key, remaining_qty_by_name = fetch_purchase_order_items([po.name])
			self.assertEqual(len(rows_by_key), 100)
			self.assertEqual(len(remaining_qty_by_name), 100)
			self.assertIn((po.name, "1"), rows_by_key)
			self.assertIn((po.name, "100"), rows_by_key)
		finally:
			if po.docstatus == 1:
				po.cancel()
			po.delete()

	def test_validate_qty_within_remaining_raises_on_excess(self):
		with self.assertRaises(PortalValidationError):
			validate_qty_within_remaining(
				purchase_order_item="FAKE",
				qty=999,
				row_number=1,
				invoice_no=None,
				remaining_qty_by_name={"FAKE": 5.0},
			)

	def test_validate_invoice_group_consistency_raises_on_mismatch(self):
		row1 = ParsedBulkRow(
			1,
			"INV-MISMATCH",
			_test_dates()["supplier_invoice_date"],
			_test_dates()["expected_delivery_date"],
			"LR-001",
			"",
			"",
			"",
			"",
			100.0,
			"PO-001",
			"1",
			"ITEM-001",
			10.0,
			25.0,
		)
		row2 = ParsedBulkRow(
			2,
			"INV-MISMATCH",
			_test_dates()["supplier_invoice_date"],
			_test_dates()["expected_delivery_date"],
			"LR-002",
			"",
			"",
			"",
			"",
			100.0,
			"PO-001",
			"2",
			"ITEM-002",
			5.0,
			35.0,
		)

		with self.assertRaises(PortalValidationError):
			validate_invoice_group_consistency("INV-MISMATCH", [row1, row2])

	def test_validate_no_duplicate_po_sr_no_raises_on_duplicate(self):
		row1 = ParsedBulkRow(
			1,
			"INV-DUP-1",
			_test_dates()["supplier_invoice_date"],
			_test_dates()["expected_delivery_date"],
			"",
			"",
			"",
			"",
			"",
			100.0,
			"PO-DUP",
			"1",
			"ITEM-001",
			10.0,
			25.0,
		)
		row2 = ParsedBulkRow(
			2,
			"INV-DUP-2",
			_test_dates()["supplier_invoice_date"],
			_test_dates()["expected_delivery_date"],
			"",
			"",
			"",
			"",
			"",
			50.0,
			"PO-DUP",
			"1",
			"ITEM-001",
			5.0,
			25.0,
		)

		with self.assertRaises(PortalValidationError):
			validate_no_duplicate_po_sr_no([row1, row2], invoice_no="INV-DUP")
