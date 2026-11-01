import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from asn_module.stock_cap.fetch import fetch_cap_context
from asn_module.stock_cap.models import Line
from asn_module.utils.test_setup import (
	apply_item_site_requirements,
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
)

BRANCH = "_Test Fetch Branch"
ITEM = "_Test Fetch Item"


def _company():
	return frappe.db.get_value("Company", {}, "name")


def _warehouse(name: str) -> str:
	abbr = frappe.get_cached_value("Company", _company(), "abbr")
	full_name = f"{name} - {abbr}"
	if not frappe.db.exists("Warehouse", full_name):
		frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": name, "company": _company(), "is_group": 0}
		).insert(ignore_permissions=True)
	return full_name


class TestStockCapFetch(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()
		if not frappe.db.exists("Branch", BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item", ITEM):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": ITEM,
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				}
			)
			apply_item_site_requirements(item)
			item.insert(ignore_permissions=True)

	def setUp(self):
		self.warehouse = _warehouse("_Test Fetch WH")
		frappe.db.delete("ASN Item Branch Cap")
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": ITEM, "max_qty": 100}
		).insert(ignore_permissions=True)

	def _line(self) -> Line:
		return Line(branch=BRANCH, item_code=ITEM, warehouse=self.warehouse, stock_qty=1.0, row_idx=1)

	def _make_settings(self, enabled: int = 1, warehouses: list[str] | None = None):
		rows = [self.warehouse] if warehouses is None else warehouses
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": BRANCH,
				"enabled": enabled,
				"warehouses": [{"warehouse": w} for w in rows],
			}
		).insert(ignore_permissions=True)

	def test_no_settings_document_yields_no_cap_warehouses(self):
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_disabled_settings_yields_no_cap_warehouses(self):
		self._make_settings(enabled=0)
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_empty_warehouse_table_yields_no_cap_warehouses(self):
		self._make_settings(warehouses=[])
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_enabled_settings_expose_cap_warehouses(self):
		self._make_settings()
		context = fetch_cap_context([self._line()])
		self.assertEqual(context.cap_warehouses, {BRANCH: frozenset({self.warehouse})})

	def test_cap_warehouses_survive_a_branch_rename(self):
		"""ASN Stock Cap Settings autonames from ``branch`` (field:branch) but has no rename
		handling. ``frappe.rename_doc`` on the Branch updates this settings document's
		``branch`` field (a Link to Branch) via its generic dependent-Link update -- it does
		not rename or re-derive the settings document itself, so the document keeps its old
		name while ``branch`` already points at the new one. ``_fetch_cap_warehouses`` must
		still find this branch's cap warehouses under the new name; before the fix it matched
		on ``settings.name`` and silently returned nothing, which -- because the module fails
		open -- meant enforcement stopped for the renamed branch with no error at all.
		"""
		self._make_settings()
		new_branch = f"{BRANCH} Renamed"
		if frappe.db.exists("Branch", new_branch):
			frappe.delete_doc("Branch", new_branch, ignore_permissions=True, force=True)

		try:
			frappe.rename_doc("Branch", BRANCH, new_branch, force=True)

			settings_name = frappe.db.get_value("ASN Stock Cap Settings", {"branch": new_branch}, "name")
			self.assertEqual(
				settings_name,
				BRANCH,
				"the settings document must keep its old (stale) name across the rename -- "
				"that stale name is exactly what this regression guards against",
			)

			line = Line(branch=new_branch, item_code=ITEM, warehouse=self.warehouse, stock_qty=1.0, row_idx=1)
			context = fetch_cap_context([line])

			self.assertEqual(context.cap_warehouses, {new_branch: frozenset({self.warehouse})})
		finally:
			# Restore the branch name so later tests in this class (and BRANCH-keyed fixtures
			# from setUp, since FrappeTestCase only rolls back at class teardown) see BRANCH
			# again.
			if frappe.db.exists("Branch", new_branch):
				frappe.rename_doc("Branch", new_branch, BRANCH, force=True)

	def test_max_stock_is_read_from_the_branch_cap_row(self):
		self._make_settings()
		self.assertEqual(fetch_cap_context([self._line()]).max_stock[(BRANCH, ITEM)], 100.0)

	def test_duplicate_cap_rows_use_the_tighter_ceiling(self):
		self._make_settings()
		other = "_Test Fetch Item Duplicate"
		if not frappe.db.exists("Item", other):
			other_item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": other,
					"item_name": other,
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				}
			)
			apply_item_site_requirements(other_item)
			other_item.insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": other, "max_qty": 4}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"ASN Item Branch Cap",
			{"branch": BRANCH, "item": other},
			"item",
			ITEM,
			update_modified=False,
		)

		self.assertEqual(fetch_cap_context([self._line()]).max_stock[(BRANCH, ITEM)], 4.0)

	def test_cap_row_for_another_branch_is_not_returned(self):
		self._make_settings()
		other = "_Test Fetch Branch Other"
		if not frappe.db.exists("Branch", other):
			frappe.get_doc({"doctype": "Branch", "branch": other}).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": other, "item": ITEM, "max_qty": 7}
		).insert(ignore_permissions=True)

		max_stock = fetch_cap_context([self._line()]).max_stock

		self.assertEqual(max_stock, {(BRANCH, ITEM): 100.0})

	def test_missing_cap_table_yields_empty_caps(self):
		self._make_settings()
		original = frappe.db.table_exists

		def fake_table_exists(doctype, *args, **kwargs):
			if doctype == "ASN Item Branch Cap":
				return False
			return original(doctype, *args, **kwargs)

		frappe.db.table_exists = fake_table_exists
		try:
			self.assertEqual(fetch_cap_context([self._line()]).max_stock, {})
		finally:
			frappe.db.table_exists = original

	def test_missing_bin_rows_coalesce_to_zero(self):
		self._make_settings()
		context = fetch_cap_context([self._line()])
		self.assertEqual(context.on_hand.get((BRANCH, ITEM), 0.0), 0.0)

	def test_no_lines_returns_empty_context(self):
		context = fetch_cap_context([])
		self.assertEqual(context.cap_warehouses, {})
		self.assertEqual(context.max_stock, {})
		self.assertEqual(context.on_hand, {})
		self.assertEqual(context.in_transit, {})


def _create_purchase_order(create_purchase_order, **kwargs):
	"""Build a real Purchase Order fixture via test_asn.create_purchase_order.

	See asn_module.utils.test_setup.build_purchase_order_with_mandatory_fields for why
	this bench-specific mandatory-field workaround is needed.
	"""
	return build_purchase_order_with_mandatory_fields(
		create_purchase_order,
		tax_description="_Test Stock Cap Fetch Tax",
		**kwargs,
	)


class TestStockCapFetchInTransit(FrappeTestCase):
	"""In-transit behaviour needs real submitted ASNs, so it lives in its own class."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

	def setUp(self):
		from asn_module.asn_module.doctype.asn.test_asn import (
			create_purchase_order,
			make_test_asn,
		)

		# FrappeTestCase only rolls back once at class teardown, not per test (see
		# frappe.deprecation_dumpster.FrappeTestCase.setUpClass), so a submitted ASN
		# from an earlier test in this class would otherwise keep contributing to later
		# in-transit totals. Clear this test class's own ASN fixtures before each test.
		stale_asn_names = frappe.get_all("ASN Item", filters={"item_code": "_Test ASN Item"}, pluck="parent")
		if stale_asn_names:
			frappe.db.delete("ASN Item", {"parent": ["in", stale_asn_names]})
			frappe.db.delete("ASN", {"name": ["in", stale_asn_names]})

		self.purchase_order = _create_purchase_order(create_purchase_order)
		self.po_item = self.purchase_order.items[0]
		# This class only asserts in-transit figures, never cap enforcement. Removing any cap
		# row for the PO item keeps a stray fixture from making self.asn.submit() below raise
		# Stock Cap Exceeded.
		frappe.db.delete("ASN Item Branch Cap", {"item": self.po_item.item_code})
		self.branch = BRANCH
		if not frappe.db.exists("Branch", self.branch):
			frappe.get_doc({"doctype": "Branch", "branch": self.branch}).insert(ignore_permissions=True)
		frappe.db.set_value("Purchase Order", self.purchase_order.name, "branch", self.branch)

		self.warehouse = self.po_item.warehouse
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": self.branch,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

		self.asn = make_test_asn(purchase_order=self.purchase_order, qty=7)
		self.asn.insert()
		self.asn.submit()

	def _line(self) -> Line:
		return Line(
			branch=self.branch,
			item_code=self.po_item.item_code,
			warehouse=self.warehouse,
			stock_qty=1.0,
			row_idx=1,
		)

	def _in_transit(self, exclude=None) -> float:
		context = fetch_cap_context([self._line()], exclude_asn_name=exclude)
		return context.in_transit.get((self.branch, self.po_item.item_code), 0.0)

	def test_submitted_asn_contributes_to_in_transit(self):
		self.assertEqual(self._in_transit(), 7.0 * (self.po_item.conversion_factor or 1))

	def test_exclude_asn_name_removes_that_asn(self):
		self.assertEqual(self._in_transit(exclude=self.asn.name), 0.0)

	def test_received_status_is_excluded(self):
		frappe.db.set_value("ASN", self.asn.name, "status", "Received", update_modified=False)
		self.assertEqual(self._in_transit(), 0.0)

	def test_closed_status_is_excluded(self):
		frappe.db.set_value("ASN", self.asn.name, "status", "Closed", update_modified=False)
		self.assertEqual(self._in_transit(), 0.0)

	def test_cancelled_asn_is_excluded(self):
		self.asn.cancel()
		self.assertEqual(self._in_transit(), 0.0)

	def test_received_qty_is_deducted_from_in_transit(self):
		frappe.db.set_value("ASN Item", self.asn.items[0].name, "received_qty", 3, update_modified=False)
		expected = 4.0 * (self.po_item.conversion_factor or 1)
		self.assertEqual(self._in_transit(), expected)

	def test_over_received_line_clamps_to_zero_rather_than_going_negative(self):
		frappe.db.set_value("ASN Item", self.asn.items[0].name, "received_qty", 99, update_modified=False)
		self.assertEqual(self._in_transit(), 0.0)


class TestStockCapFetchPoItemReceivingQty(FrappeTestCase):
	"""po_item_receiving_qty is the Purchase Receipt path's correction mechanism (see
	breaches_for_purchase_receipt). Unlike exclude_asn_name -- which drops every ASN Item
	belonging to the excluded ASN -- it subtracts only the stock-UOM quantity a receipt is
	actually receiving from the specific Purchase Order Item's in-transit subtotal, clamped
	at zero, so a sibling item on the same ASN the receipt does not cover, the still-
	undelivered remainder of a partially received item, and a second ASN shipping the same
	Purchase Order Item all keep contributing their own outstanding quantity to in-transit.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

		if not frappe.db.exists("Branch", cls.branch_name()):
			frappe.get_doc({"doctype": "Branch", "branch": cls.branch_name()}).insert(ignore_permissions=True)
		for item_code in (cls.item_a_name(), cls.item_b_name()):
			if not frappe.db.exists("Item", item_code):
				item = frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": item_code,
						"item_name": item_code,
						"item_group": frappe.db.get_value("Item Group", {}, "name"),
						"stock_uom": frappe.db.get_value("UOM", {}, "name"),
					}
				)
				apply_item_site_requirements(item)
				item.insert(ignore_permissions=True)

	@classmethod
	def branch_name(cls) -> str:
		return "_Test Fetch ExcludePO Branch"

	@classmethod
	def item_a_name(cls) -> str:
		return "_Test Fetch ExcludePO Item A"

	@classmethod
	def item_b_name(cls) -> str:
		return "_Test Fetch ExcludePO Item B"

	def setUp(self):
		from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

		self.branch = self.branch_name()
		self.item_a = self.item_a_name()
		self.item_b = self.item_b_name()

		# FrappeTestCase only rolls back once at class teardown, not per test.
		stale_asn_names = frappe.get_all(
			"ASN Item", filters={"item_code": ["in", [self.item_a, self.item_b]]}, pluck="parent"
		)
		if stale_asn_names:
			frappe.db.delete("ASN Item", {"parent": ["in", stale_asn_names]})
			frappe.db.delete("ASN", {"name": ["in", stale_asn_names]})
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")

		# Let the Purchase Order resolve create_purchase_order's own default warehouse
		# rather than handing it one built separately: a hand-picked Warehouse must
		# belong to the same Company create_purchase_order defaults to, or Purchase
		# Order validation rejects it.
		# One Purchase Order, two lines. An ASN can name only one order, and the
		# sibling assertions below need both lines on that same notice.
		create_purchase_order(item_code=self.item_b, do_not_save=True, qty=10)
		po_a = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap Fetch ExcludePO Tax A",
			item_code=self.item_a,
			# 20, not the default 10: test_two_asns_for_the_same_po_item_... ships a second
			# 5-unit ASN against this same Purchase Order Item on top of setUp's own 7, and
			# ASN._validate_po_qty rejects shipping more than the PO's remaining qty.
			qty=20,
			do_not_submit=True,
		)
		self.warehouse = po_a.items[0].warehouse
		po_a.append(
			"items",
			{
				"item_code": self.item_b,
				"warehouse": self.warehouse,
				"qty": 10,
				"rate": po_a.items[0].rate,
				"schedule_date": po_a.items[0].schedule_date,
			},
		)
		po_a.save()
		po_a.submit()
		frappe.db.set_value("Purchase Order", po_a.name, "branch", self.branch)

		self.po_a = po_a
		self.po_item_a = po_a.items[0]
		self.po_item_b = po_a.items[1]

		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": self.branch,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

		self.asn = self._make_and_submit_asn(
			supplier=po_a.supplier,
			items=[
				{
					"purchase_order": po_a.name,
					"purchase_order_item": self.po_item_a.name,
					"item_code": self.item_a,
					"qty": 7,
					"uom": self.po_item_a.uom,
					"rate": self.po_item_a.rate,
				},
				{
					"purchase_order": po_a.name,
					"purchase_order_item": self.po_item_b.name,
					"item_code": self.item_b,
					"qty": 4,
					"uom": self.po_item_b.uom,
					"rate": self.po_item_b.rate,
				},
			],
		)

	def _make_and_submit_asn(self, *, supplier, items):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": supplier,
				"supplier_invoice_no": f"INV-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"expected_delivery_date": today(),
				"supplier_invoice_amount": sum(flt(row.get("qty")) * flt(row.get("rate")) for row in items),
				"vehicle_number": "MH12AB1234",
				"items": items,
			}
		)
		asn.insert(ignore_permissions=True)
		asn.submit()
		return asn

	def _line(self, item_code) -> Line:
		return Line(
			branch=self.branch, item_code=item_code, warehouse=self.warehouse, stock_qty=1.0, row_idx=1
		)

	def _stock_qty(self, po_item, purchase_uom_qty: float) -> float:
		return purchase_uom_qty * (po_item.conversion_factor or 1)

	def _in_transit(self, item_code, po_item_receiving_qty=None) -> float:
		context = fetch_cap_context(
			[self._line(self.item_a), self._line(self.item_b)],
			po_item_receiving_qty=po_item_receiving_qty,
		)
		return context.in_transit.get((self.branch, item_code), 0.0)

	def test_po_item_receiving_qty_removes_only_the_matching_po_item(self):
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 7)}
		self.assertEqual(self._in_transit(self.item_a, receiving), 0.0)

	def test_po_item_receiving_qty_keeps_a_sibling_items_unreceived_remainder_counted(self):
		"""Regression for the partial-receipt under-count: excluding the whole ASN by name
		used to drop every item's in-transit total, not just the item a receipt actually
		covers. Subtracting only the receipt's own receiving quantity, keyed by Purchase
		Order Item, must leave a sibling item on the same ASN -- one this receipt does not
		cover -- still fully counted.
		"""
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 7)}
		expected_b = self._stock_qty(self.po_item_b, 4)
		self.assertEqual(self._in_transit(self.item_b, receiving), expected_b)

	def test_no_po_item_receiving_qty_counts_both(self):
		expected_a = self._stock_qty(self.po_item_a, 7)
		expected_b = self._stock_qty(self.po_item_b, 4)
		self.assertEqual(self._in_transit(self.item_a), expected_a)
		self.assertEqual(self._in_transit(self.item_b), expected_b)

	def test_partial_receipt_leaves_the_undelivered_remainder_counted(self):
		"""This is the bug this class guards against: the ASN shipped 7 units of PO item
		A and none of it has been received yet (received_qty is still 0 at before_submit),
		so a receipt taking only 3 of those 7 units must leave the other 4 counted as
		in-transit -- not zero it out as the old whole-row exclusion did.
		"""
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 3)}
		expected_remainder = self._stock_qty(self.po_item_a, 4)
		self.assertEqual(self._in_transit(self.item_a, receiving), expected_remainder)

	def test_two_asns_for_the_same_po_item_leaves_the_other_asns_shipment_counted(self):
		"""A single Purchase Order Item can be shipped across more than one ASN. A receipt
		that exactly covers the first ASN's shipment must not remove the second ASN's still-
		undelivered quantity -- only its own receiving quantity comes off the combined total.
		"""
		self._make_and_submit_asn(
			supplier=self.po_a.supplier,
			items=[
				{
					"purchase_order": self.po_a.name,
					"purchase_order_item": self.po_item_a.name,
					"item_code": self.item_a,
					"qty": 5,
					"uom": self.po_item_a.uom,
					"rate": self.po_item_a.rate,
				}
			],
		)

		# Before any receipt, both ASNs' shipments of PO item A are in-transit.
		self.assertEqual(self._in_transit(self.item_a), self._stock_qty(self.po_item_a, 12))

		# A receipt that exactly covers the first ASN's 7 units must leave the second
		# ASN's 5 still-undelivered units counted.
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 7)}
		expected_remainder = self._stock_qty(self.po_item_a, 5)
		self.assertEqual(self._in_transit(self.item_a, receiving), expected_remainder)

	def test_full_receipt_zeroes_out_in_transit_without_going_negative(self):
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 7)}
		self.assertEqual(self._in_transit(self.item_a, receiving), 0.0)

	def test_over_receiving_a_po_item_clamps_to_zero_without_borrowing_from_a_sibling(self):
		"""fetch.py:_fetch_in_transit clamps the subtraction at zero per Purchase Order
		Item, before pooling into the item_code/warehouse total the evaluator reads. An
		over-receipt of PO item A must not lend negative in-transit to item B's own total,
		even though both items share this test's one warehouse.
		"""
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 999)}
		expected_b = self._stock_qty(self.po_item_b, 4)
		self.assertEqual(self._in_transit(self.item_a, receiving), 0.0)
		self.assertEqual(self._in_transit(self.item_b, receiving), expected_b)

	def test_over_receiving_a_po_item_clamps_to_zero_without_borrowing_from_a_same_item_sibling(self):
		"""The risk the clamp was actually written for: item_a and item_b above are two
		*distinct* item codes, so pooling their (already non-negative) subtotals together
		can never exercise a negative-borrowing bug -- two positive numbers summed can't go
		negative regardless of where the clamp sits. The real risk is two distinct Purchase
		Order Items that share one item_code and one warehouse: the evaluator pools their
		in-transit by (item_code, warehouse), so if the per-PO-Item clamp in
		_fetch_in_transit ran after pooling instead of before, an enormous over-receipt
		against one PO Item could drag the shared item_code/warehouse total negative and
		silently cancel out a sibling PO Item's own still-undelivered quantity. Pin that the
		clamp is per-PO-Item and applied before pooling, so this cannot happen.
		"""
		from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

		po_c = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap Fetch ExcludePO Tax C",
			item_code=self.item_a,
			warehouse=self.warehouse,
			supplier=self.po_a.supplier,
		)
		frappe.db.set_value("Purchase Order", po_c.name, "branch", self.branch)
		po_item_c = po_c.items[0]

		self._make_and_submit_asn(
			supplier=po_c.supplier,
			items=[
				{
					"purchase_order": po_c.name,
					"purchase_order_item": po_item_c.name,
					"item_code": self.item_a,
					"qty": 5,
					"uom": po_item_c.uom,
					"rate": po_item_c.rate,
				}
			],
		)

		# Massively over-receive po_item_a (999 units against a 7-unit shipment). If the
		# clamp ran after pooling instead of per-PO-Item, this would drag item_a's pooled
		# total negative and eat into po_item_c's own still-undelivered 5 units.
		receiving = {self.po_item_a.name: self._stock_qty(self.po_item_a, 999)}
		expected_remainder = self._stock_qty(po_item_c, 5)
		self.assertEqual(self._in_transit(self.item_a, receiving), expected_remainder)
