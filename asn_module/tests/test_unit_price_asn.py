"""A unit-price Purchase Order line has a rate and an ordered quantity of zero.

The supplier can still declare an ASN when the quantity fits the branch stock cap.
A line with no cap configured stays open. A zero quantity that is not a unit-price
line is still refused by the ordered-quantity check.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.asn import get_purchase_order_items
from asn_module.asn_module.doctype.asn.test_asn import (
	_ensure_item,
	create_purchase_order,
	make_test_asn,
)
from asn_module.templates.pages.asn_new_search import search_purchase_order_items
from asn_module.templates.pages.asn_new_services import (
	PortalValidationError,
	validate_qty_within_remaining,
)
from asn_module.utils.test_setup import (
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
	resolve_test_company,
)

BRANCH = "_Test Unit Price Cap Branch"
MAX_STOCK = 4


class TestUnitPricePurchaseOrderAsn(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()
		if not frappe.db.exists("Branch", BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
		_ensure_item()
		# The portal search lists at most 200 open POs per supplier; the shared
		# "_Test ASN Supplier" accrues committed residue on dev sites, drowning a
		# test's own PO. Isolate the class on its own supplier.
		supplier_name = "_Test Unit Price Supplier"
		if not frappe.db.exists("Supplier", supplier_name):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": supplier_name,
					"supplier_type": "Company",
					"supplier_group": frappe.db.get_value("Supplier Group", {}, "name")
					or "All Supplier Groups",
				}
			).insert(ignore_permissions=True)
		cls.supplier = supplier_name

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		# A dedicated warehouse keeps on-hand stock at zero: the shared company
		# warehouse on a production-clone site carries residue stock of the test
		# item from earlier committed runs, which silently eats cap headroom.
		self.warehouse = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"_Test Unit Price Cap WH {frappe.generate_hash(length=5)}",
					"company": resolve_test_company(),
					"is_group": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Unit Price ASN Tax",
			supplier=self.supplier,
			qty=10,
			warehouse=self.warehouse,
			do_not_submit=True,
		)
		self.item_code = self.po.items[0].item_code
		frappe.db.set_value(
			"Purchase Order",
			self.po.name,
			{"has_unit_price_items": 1, "branch": BRANCH},
		)
		frappe.db.set_value("Purchase Order Item", self.po.items[0].name, "qty", 0)
		frappe.db.delete("ASN Item Branch Cap", {"item": self.item_code, "branch": BRANCH})
		# This bench rolls the test class back once, so a prior test's shipment would
		# still sit in transit and fill the cap. Drop those rows before measuring headroom.
		frappe.db.delete("ASN Item", {"item_code": self.item_code})

	def _enable_cap(self, max_qty: float = MAX_STOCK):
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": self.item_code, "max_qty": max_qty}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": BRANCH,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

	def test_a_unit_price_line_within_the_branch_cap_is_offered_and_submits(self):
		self._enable_cap()

		offered = get_purchase_order_items(self.po.name)
		self.assertEqual(len(offered), 1)
		self.assertEqual(offered[0]["item_code"], self.item_code)
		self.assertEqual(offered[0]["qty"], MAX_STOCK)

		asn = make_test_asn(purchase_order=self.po, qty=MAX_STOCK)
		asn.insert(ignore_permissions=True)
		asn.submit()

		self.assertEqual(asn.docstatus, 1)
		self.assertEqual(asn.items[0].qty, MAX_STOCK)

	def test_a_unit_price_line_over_the_branch_cap_is_refused(self):
		self._enable_cap()

		with self.assertRaises(PortalValidationError) as raised:
			validate_qty_within_remaining(
				purchase_order_item=self.po.items[0].name,
				qty=MAX_STOCK + 1,
				row_number=2,
				invoice_no=None,
				remaining_qty_by_name=self._remaining(),
			)
		self.assertIn(str(MAX_STOCK), str(raised.exception))

		asn = make_test_asn(purchase_order=self.po, qty=MAX_STOCK + 1)
		asn.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError) as submit_error:
			asn.submit()
		self.assertIn("exceeds maximum", str(submit_error.exception))

	def test_a_unit_price_line_with_no_branch_cap_is_offered_and_submits(self):
		offered = get_purchase_order_items(self.po.name)
		self.assertEqual([row["item_code"] for row in offered], [self.item_code])
		self.assertEqual(offered[0]["qty"], 1)

		validate_qty_within_remaining(
			purchase_order_item=self.po.items[0].name,
			qty=25,
			row_number=2,
			invoice_no=None,
			remaining_qty_by_name=self._remaining(),
		)

		asn = make_test_asn(purchase_order=self.po, qty=25)
		asn.insert(ignore_permissions=True)
		asn.submit()
		self.assertEqual(asn.docstatus, 1)

	def test_portal_search_offers_a_capped_unit_price_line(self):
		self._enable_cap()
		with (
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier",
				return_value=self.po.supplier,
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[frappe._dict(name=self.po.name)],
			),
		):
			rows = search_purchase_order_items(self.po.name)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["remaining_qty"], MAX_STOCK)
		self.assertEqual(rows[0]["purchase_order_item"], self.po.items[0].name)

	def _remaining(self):
		from asn_module.asn_module.doctype.asn.asn import remaining_qty_by_purchase_order_item

		return remaining_qty_by_purchase_order_item({self.po.items[0].name: 0})
