from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages import asn_new_search
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def _test_dates():
	cache_key = "_asn_new_search_test_dates_cache"
	cached = getattr(frappe.local, cache_key, None)
	if cached is None:
		cached = get_fiscal_year_test_dates()
		setattr(frappe.local, cache_key, cached)
	return cached


class TestASNNewSearch(FrappeTestCase):
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
				"asn_module.templates.pages.asn_new_search._get_shipped_qty_by_po_item",
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
				"asn_module.templates.pages.asn_new_search._get_shipped_qty_by_po_item",
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
				"asn_module.templates.pages.asn_new_search._get_shipped_qty_by_po_item",
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
				"asn_module.templates.pages.asn_new_search._get_shipped_qty_by_po_item",
				return_value={"POI-1": 0},
			),
		):
			rows = asn_new_search.search_purchase_order_items(
				purchase_order="PO-0001", txt="", start="0", page_len="200"
			)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-001")
