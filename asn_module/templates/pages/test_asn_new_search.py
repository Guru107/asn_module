from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages import asn_new_search
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def _test_dates():
	return get_fiscal_year_test_dates()


class TestASNNewSearch(FrappeTestCase):
	def test_normalize_paging_falls_back_for_invalid_values(self):
		start, page_len = asn_new_search._normalize_paging("not-a-number", None)
		self.assertEqual(start, 0)
		self.assertEqual(page_len, 20)

	def test_normalize_paging_clamps_negative_and_zero_values(self):
		start, page_len = asn_new_search._normalize_paging("-10", "0")
		self.assertEqual(start, 0)
		self.assertEqual(page_len, 1)

	def test_search_open_purchase_orders_returns_supplier_open_pos(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					),
					SimpleNamespace(
						name="PO-0002",
						status="To Receive and Bill",
						transaction_date=_test_dates()["expected_delivery_date"],
					),
				],
			),
		):
			rows = asn_new_search.search_open_purchase_orders(txt="PO-0001")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "PO-0001")

	def test_search_purchase_order_items_rejects_po_outside_supplier_scope(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					)
				],
			),
			self.assertRaises(frappe.PermissionError),
		):
			asn_new_search.search_purchase_order_items(purchase_order="PO-9999", txt="")

	def test_search_purchase_order_items_filters_by_po_and_text(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					)
				],
			),
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.get_all",
				return_value=[
					SimpleNamespace(
						name="POI-1",
						idx=1,
						item_code="ITEM-001",
						item_name="Widget 1",
						uom="Nos",
						rate=10,
						qty=5,
					),
					SimpleNamespace(
						name="POI-2",
						idx=2,
						item_code="ABC-002",
						item_name="Widget 2",
						uom="Nos",
						rate=20,
						qty=4,
					),
				],
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn._unreceived_qty_by_po_item",
				return_value={"POI-1": 2, "POI-2": 4},
			),
		):
			rows = asn_new_search.search_purchase_order_items(purchase_order="PO-0001", txt="ITEM")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-001")
		self.assertEqual(rows[0]["sr_no"], "1")
		self.assertEqual(rows[0]["item_name"], "Widget 1")
		self.assertEqual(rows[0]["remaining_qty"], 3)

	def test_get_supplier_raises_when_none(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="no-supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value=None),
			self.assertRaises(frappe.PermissionError),
		):
			asn_new_search._get_supplier()

	def test_search_open_purchase_orders_empty_txt_returns_all(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					),
					SimpleNamespace(
						name="PO-0002",
						status="To Receive",
						transaction_date=_test_dates()["expected_delivery_date"],
					),
				],
			),
		):
			rows = asn_new_search.search_open_purchase_orders(txt="")
		self.assertEqual(len(rows), 2)

	def test_search_purchase_order_items_with_txt_filter(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					)
				],
			),
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.get_all",
				return_value=[
					SimpleNamespace(
						name="POI-1",
						idx=1,
						item_code="ITEM-001",
						item_name="Alpha",
						uom="Nos",
						rate=10,
						qty=5,
					),
					SimpleNamespace(
						name="POI-2",
						idx=2,
						item_code="OTHER-002",
						item_name="Beta",
						uom="Nos",
						rate=20,
						qty=5,
					),
				],
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn._unreceived_qty_by_po_item",
				return_value={"POI-1": 0, "POI-2": 0},
			),
		):
			rows = asn_new_search.search_purchase_order_items(purchase_order="PO-0001", txt="alpha")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-001")

	def test_search_purchase_order_items_excludes_fully_received_rows(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					)
				],
			),
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.get_all",
				return_value=[
					SimpleNamespace(
						name="POI-1",
						idx=1,
						item_code="ITEM-001",
						item_name="Alpha",
						uom="Nos",
						rate=10,
						qty=5,
					),
					SimpleNamespace(
						name="POI-2", idx=2, item_code="ITEM-002", item_name="Beta", uom="Nos", rate=20, qty=2
					),
				],
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn._unreceived_qty_by_po_item",
				return_value={"POI-1": 5, "POI-2": 0},
			),
		):
			rows = asn_new_search.search_purchase_order_items(purchase_order="PO-0001", txt="")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-002")

	def test_search_purchase_order_items_accepts_string_paging_params(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(
						name="PO-0001",
						status="To Receive",
						transaction_date=_test_dates()["supplier_invoice_date"],
					)
				],
			),
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.get_all",
				return_value=[
					SimpleNamespace(
						name="POI-1",
						idx=1,
						item_code="ITEM-001",
						item_name="Alpha",
						uom="Nos",
						rate=10,
						qty=5,
					),
				],
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn._unreceived_qty_by_po_item",
				return_value={"POI-1": 0},
			),
		):
			rows = asn_new_search.search_purchase_order_items(
				purchase_order="PO-0001", txt="", start="0", page_len="200"
			)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-001")

	def test_search_open_subcontracting_orders_returns_the_suppliers_open_order(self):
		from asn_module.handlers.tests.test_subcontracting import TestSubcontractingHandlers

		sco = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value=sco.supplier,
			),
		):
			rows = asn_new_search.search_open_subcontracting_orders(txt="")
			closed = asn_new_search.search_open_subcontracting_orders(txt="missing")
		self.assertIn(sco.name, [row["value"] for row in rows])
		self.assertEqual(closed, [])
		frappe.db.set_value("Subcontracting Order", sco.name, "status", "Closed")
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value=sco.supplier,
			),
		):
			after_close = asn_new_search.search_open_subcontracting_orders(txt=sco.name)
		self.assertEqual(after_close, [])

	def test_search_subcontracting_order_items_returns_the_open_finished_good(self):
		from asn_module.handlers.tests.test_subcontracting import TestSubcontractingHandlers

		sco = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = sco.items[0]
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value=sco.supplier,
			),
		):
			rows = asn_new_search.search_subcontracting_order_items(subcontracting_order=sco.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], finished_good.item_code)
		self.assertEqual(rows[0]["subcontracting_order_item"], finished_good.name)
		self.assertEqual(rows[0]["remaining_qty"], finished_good.qty)
		frappe.db.set_value(
			"Subcontracting Order Item", finished_good.name, "received_qty", finished_good.qty
		)
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value=sco.supplier,
			),
		):
			received = asn_new_search.search_subcontracting_order_items(subcontracting_order=sco.name)
		self.assertEqual(len(received), 1)
		self.assertEqual(received[0]["remaining_qty"], 0)
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value="someone-else",
			),
		):
			with self.assertRaises(frappe.PermissionError):
				asn_new_search.search_subcontracting_order_items(subcontracting_order=sco.name)
