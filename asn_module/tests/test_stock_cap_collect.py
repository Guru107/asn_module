from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
)
from asn_module.utils.test_setup import (
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
)


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

	def test_rejected_qty_treats_zero_conversion_factor_as_one(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[
				_receipt_row(
					stock_qty=0.0,
					rejected_qty=4.0,
					rejected_warehouse="Quarantine - MC",
					conversion_factor=0.0,
				)
			],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].warehouse, "Quarantine - MC")
		self.assertEqual(lines[0].stock_qty, 4.0)

	def test_rejected_qty_treats_none_conversion_factor_as_one(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[
				_receipt_row(
					stock_qty=0.0,
					rejected_qty=4.0,
					rejected_warehouse="Quarantine - MC",
					conversion_factor=None,
				)
			],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].warehouse, "Quarantine - MC")
		self.assertEqual(lines[0].stock_qty, 4.0)


def _ensure_branch(name: str) -> str:
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)
	return name


def _create_purchase_order(**kwargs):
	"""Build a real Purchase Order fixture via test_asn.create_purchase_order.

	See asn_module.utils.test_setup.build_purchase_order_with_mandatory_fields for why
	this bench-specific mandatory-field workaround is needed.
	"""
	from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

	do_not_submit = kwargs.pop("do_not_submit", False)
	return build_purchase_order_with_mandatory_fields(
		create_purchase_order,
		tax_description="_Test Stock Cap Tax",
		do_not_submit=do_not_submit,
		**kwargs,
	)


def _ensure_extra_warehouse(name: str) -> str:
	company = frappe.db.get_value("Company", {}, "name")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full_name = f"{name} - {abbr}"
	if frappe.db.exists("Warehouse", full_name):
		return full_name

	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": name,
			"company": company,
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestStockCapCollectASN(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

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

	def test_collect_lines_from_asn_rows_multiplies_qty_by_po_item_conversion_factor(self):
		branch = _ensure_branch("_Test Stock Cap Collect Branch")
		purchase_order = _create_purchase_order(qty=10)
		po_item = purchase_order.items[0]
		frappe.db.set_value("Purchase Order", purchase_order.name, "branch", branch)
		frappe.db.set_value("Purchase Order Item", po_item.name, "conversion_factor", 3.0)

		rows = [
			{
				"idx": 1,
				"purchase_order": purchase_order.name,
				"purchase_order_item": po_item.name,
				"item_code": po_item.item_code,
				"qty": 5.0,
			}
		]

		lines = collect_lines_from_asn_rows(rows)

		self.assertEqual(len(lines), 1)
		line = lines[0]
		self.assertEqual(line.stock_qty, 15.0)
		self.assertEqual(line.branch, branch)
		self.assertEqual(line.item_code, po_item.item_code)
		self.assertEqual(line.warehouse, po_item.warehouse)
		self.assertEqual(line.row_idx, 1)

	def test_collect_lines_from_asn_rows_falls_back_to_po_set_warehouse(self):
		branch = _ensure_branch("_Test Stock Cap Collect Branch")
		fallback_warehouse = _ensure_extra_warehouse("_Test Stock Cap Fallback WH")
		purchase_order = _create_purchase_order(qty=10)
		po_item = purchase_order.items[0]
		frappe.db.set_value("Purchase Order", purchase_order.name, "branch", branch)
		frappe.db.set_value("Purchase Order", purchase_order.name, "set_warehouse", fallback_warehouse)
		frappe.db.set_value("Purchase Order Item", po_item.name, "warehouse", None)

		rows = [
			{
				"idx": 1,
				"purchase_order": purchase_order.name,
				"purchase_order_item": po_item.name,
				"item_code": po_item.item_code,
				"qty": 4.0,
			}
		]

		lines = collect_lines_from_asn_rows(rows)

		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].warehouse, fallback_warehouse)

	def test_collect_lines_from_asn_rows_skips_row_with_no_warehouse_anywhere(self):
		"""Neither the PO Item warehouse nor the PO's set_warehouse fallback is set.

		Real ERPNext data normally guarantees one or the other, but nothing in the schema
		enforces it, so this row must be dropped rather than producing a Line with an empty
		warehouse (which would silently never match any cap_warehouses entry downstream).
		"""
		branch = _ensure_branch("_Test Stock Cap Collect Branch")
		purchase_order = _create_purchase_order(qty=10)
		po_item = purchase_order.items[0]
		frappe.db.set_value("Purchase Order", purchase_order.name, "branch", branch)
		frappe.db.set_value("Purchase Order", purchase_order.name, "set_warehouse", None)
		frappe.db.set_value("Purchase Order Item", po_item.name, "warehouse", None)

		rows = [
			{
				"idx": 1,
				"purchase_order": purchase_order.name,
				"purchase_order_item": po_item.name,
				"item_code": po_item.item_code,
				"qty": 4.0,
			}
		]

		self.assertEqual(collect_lines_from_asn_rows(rows), [])
