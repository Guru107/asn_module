from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
)
from asn_module.utils.test_setup import before_tests


def _receipt_row(**overrides):
	defaults = {
		"idx": 1,
		"item_code": "WIDGET",
		"warehouse": "Main - MC",
		"stock_qty": 30.0,
		"rejected_qty": 0.0,
		"rejected_warehouse": None,
		"conversion_factor": 1.0,
	}
	defaults.update(overrides)
	return SimpleNamespace(**defaults)


class TestStockCapCollectPurchaseReceipt(FrappeTestCase):
	def test_receipt_lines_use_stock_qty_without_conversion(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[_receipt_row(stock_qty=30.0, conversion_factor=10.0)],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].stock_qty, 30.0)
		self.assertEqual(lines[0].warehouse, "Main - MC")
		self.assertEqual(lines[0].branch, "Mumbai")

	def test_return_receipt_produces_no_lines(self):
		doc = SimpleNamespace(branch="Mumbai", is_return=1, items=[_receipt_row(stock_qty=-30.0)])
		self.assertEqual(collect_lines_from_purchase_receipt(doc), [])

	def test_rejected_qty_becomes_its_own_line_in_rejected_warehouse(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[
				_receipt_row(
					stock_qty=20.0,
					rejected_qty=3.0,
					rejected_warehouse="Quarantine - MC",
					conversion_factor=2.0,
				)
			],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 2)
		by_warehouse = {line.warehouse: line.stock_qty for line in lines}
		self.assertEqual(by_warehouse["Main - MC"], 20.0)
		self.assertEqual(by_warehouse["Quarantine - MC"], 6.0)

	def test_rejected_qty_without_rejected_warehouse_is_dropped(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[_receipt_row(stock_qty=20.0, rejected_qty=3.0, rejected_warehouse=None)],
		)
		self.assertEqual(len(collect_lines_from_purchase_receipt(doc)), 1)

	def test_receipt_without_branch_produces_no_lines(self):
		doc = SimpleNamespace(branch=None, is_return=0, items=[_receipt_row()])
		self.assertEqual(collect_lines_from_purchase_receipt(doc), [])


class TestStockCapCollectASN(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()

	def test_asn_rows_from_doc_extracts_row_shape(self):
		doc = SimpleNamespace(
			items=[
				SimpleNamespace(
					idx=1,
					purchase_order="PO-0001",
					purchase_order_item="poi-1",
					item_code="WIDGET",
					qty=5.0,
				)
			]
		)
		self.assertEqual(
			asn_rows_from_doc(doc),
			[
				{
					"idx": 1,
					"purchase_order": "PO-0001",
					"purchase_order_item": "poi-1",
					"item_code": "WIDGET",
					"qty": 5.0,
				}
			],
		)

	def test_rows_without_purchase_order_are_skipped(self):
		rows = [{"idx": 1, "purchase_order": "", "purchase_order_item": "", "item_code": "X", "qty": 1}]
		self.assertEqual(collect_lines_from_asn_rows(rows), [])

	def test_missing_branch_column_returns_no_lines(self):
		rows = [
			{
				"idx": 1,
				"purchase_order": "PO-0001",
				"purchase_order_item": "poi-1",
				"item_code": "WIDGET",
				"qty": 1,
			}
		]
		original = frappe.db.has_column

		def fake_has_column(doctype, column):
			if doctype == "Purchase Order" and column == "branch":
				return False
			return original(doctype, column)

		frappe.db.has_column = fake_has_column
		try:
			self.assertEqual(collect_lines_from_asn_rows(rows), [])
		finally:
			frappe.db.has_column = original
