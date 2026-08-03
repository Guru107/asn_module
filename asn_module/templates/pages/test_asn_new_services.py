from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import _resolve_test_company, create_purchase_order
from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
	create_bulk_asns_for_supplier,
	enforce_bulk_limits,
	error_entry,
	fetch_purchase_order_items,
	get_supplier_open_purchase_orders,
	normalize_group_field,
	normalize_group_value,
	parse_bulk_csv_content,
	parse_non_negative_rate,
	parse_optional_non_negative_rate,
	parse_positive_qty,
	parse_required_supplier_invoice_amount,
	validate_bulk_group_count,
	validate_invoice_group_consistency,
	validate_invoice_group_single_purchase_order,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates
from asn_module.utils.test_setup import (
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
)


def _test_dates():
	return get_fiscal_year_test_dates()


def _bulk_csv_content(row_line: str) -> bytes:
	return (
		"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,"
		"transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,"
		"sr_no,item_code,qty,rate\n"
		f"{row_line}\n"
	).encode()


class TestParsePositiveQty(FrappeTestCase):
	def test_positive(self):
		self.assertEqual(parse_positive_qty("10", row_number=1, field="qty"), 10.0)

	def test_zero_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("0", row_number=1, field="qty")

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("-5", row_number=1, field="qty")

	def test_empty_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("", row_number=1, field="qty")


class TestParseNonNegativeRate(FrappeTestCase):
	def test_zero_ok(self):
		self.assertEqual(parse_non_negative_rate("0", row_number=1, field="rate"), 0.0)

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_non_negative_rate("-1", row_number=1, field="rate")

	def test_valid_returns_float(self):
		self.assertEqual(parse_non_negative_rate("25.5", row_number=1, field="rate"), 25.5)


class TestParseOptionalNonNegativeRate(FrappeTestCase):
	def test_none_returns_none(self):
		self.assertIsNone(parse_optional_non_negative_rate(None, row_number=1, field="rate"))

	def test_empty_returns_none(self):
		self.assertIsNone(parse_optional_non_negative_rate("", row_number=1, field="rate"))

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_optional_non_negative_rate("-1", row_number=1, field="rate")

	def test_valid_returns_float(self):
		self.assertEqual(parse_optional_non_negative_rate("10", row_number=1, field="rate"), 10.0)


class TestParseRequiredSupplierInvoiceAmount(FrappeTestCase):
	def test_valid(self):
		self.assertEqual(parse_required_supplier_invoice_amount("250", row_number=1), 250.0)

	def test_zero_ok(self):
		self.assertEqual(parse_required_supplier_invoice_amount("0", row_number=1), 0.0)

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_required_supplier_invoice_amount("-10", row_number=1)

	def test_empty_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_required_supplier_invoice_amount("", row_number=1)


class TestNormalizeGroupValue(FrappeTestCase):
	def test_whitespace(self):
		self.assertEqual(normalize_group_value("  hello  "), "hello")

	def test_none(self):
		self.assertEqual(normalize_group_value(None), "")

	def test_normal(self):
		self.assertEqual(normalize_group_value("hello"), "hello")


class TestServiceUtilities(FrappeTestCase):
	def test_parse_bulk_csv_content_accepts_portal_template_without_request_context(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,250,PO-0001,1,ITEM-001,10,25"
		)

		rows = parse_bulk_csv_content(csv_content)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].supplier_invoice_no, "INV-1")
		self.assertEqual(rows[0].purchase_order, "PO-0001")
		self.assertEqual(rows[0].sr_no, "1")
		self.assertEqual(rows[0].item_code, "ITEM-001")
		self.assertEqual(rows[0].qty, 10)
		self.assertEqual(rows[0].rate, 25)
		self.assertEqual(rows[0].supplier_invoice_amount, 250)

	def test_error_entry_keeps_row_invoice_field_and_message(self):
		result = error_entry(row_number=2, invoice_no="INV-1", field="qty", message="Bad qty")

		self.assertEqual(result["row_number"], 2)
		self.assertEqual(result["invoice_no"], "INV-1")
		self.assertEqual(result["field"], "qty")
		self.assertEqual(result["message"], "Bad qty")

	def test_get_supplier_open_purchase_orders_indexes_rows_by_name(self):
		rows = [SimpleNamespace(name="PO-001"), SimpleNamespace(name="PO-002")]
		with patch(
			"asn_module.templates.pages.asn_new_services.get_open_purchase_orders_for_supplier",
			return_value=rows,
		):
			result = get_supplier_open_purchase_orders("Supp-001")

		self.assertEqual(sorted(result), ["PO-001", "PO-002"])
		self.assertIs(result["PO-001"], rows[0])

	def test_fetch_purchase_order_items_returns_empty_without_purchase_orders(self):
		with patch("asn_module.templates.pages.asn_new_services.frappe.get_all") as get_all:
			result = fetch_purchase_order_items([])

		self.assertEqual(result, ({}, {}))
		get_all.assert_not_called()

	def test_fetch_purchase_order_items_groups_by_purchase_order_and_sr_no(self):
		rows = [
			frappe._dict({"name": "POI-1", "parent": "PO-1", "idx": 1, "item_code": "ITEM-1", "qty": 10}),
			frappe._dict({"name": "POI-2", "parent": "PO-1", "idx": 2, "item_code": "ITEM-2", "qty": 5}),
		]
		with (
			patch("asn_module.templates.pages.asn_new_services.frappe.get_all", return_value=rows),
			patch(
				"asn_module.templates.pages.asn_new_services._get_shipped_qty_by_po_item",
				return_value={"POI-1": 3},
			),
		):
			rows_by_key, remaining = fetch_purchase_order_items(["PO-1"])

		self.assertEqual(rows_by_key[("PO-1", "1")][0].name, "POI-1")
		self.assertEqual(remaining["POI-1"], 7)
		self.assertEqual(remaining["POI-2"], 5)


class TestNormalizeGroupField(FrappeTestCase):
	def test_supplier_invoice_amount_numeric(self):
		result = normalize_group_field("supplier_invoice_amount", "100.00")
		self.assertEqual(result, "100.0")

	def test_supplier_invoice_amount_empty(self):
		result = normalize_group_field("supplier_invoice_amount", "")
		self.assertEqual(result, "")

	def test_other_field(self):
		result = normalize_group_field("lr_no", "  LR123  ")
		self.assertEqual(result, "LR123")


class TestEnforceBulkLimits(FrappeTestCase):
	def test_within_limit_ok(self):
		rows = [SimpleNamespace()] * 10
		enforce_bulk_limits(rows)

	def test_over_limit_raises(self):
		from asn_module.templates.pages.asn_new_services import MAX_BULK_ROWS

		rows = [SimpleNamespace()] * (MAX_BULK_ROWS + 1)
		with self.assertRaises(PortalValidationError):
			enforce_bulk_limits(rows)


class TestValidateBulkGroupCount(FrappeTestCase):
	def test_within_limit_ok(self):
		groups = {"INV-" + str(i): [] for i in range(10)}
		validate_bulk_group_count(groups)

	def test_exceeds_raises(self):
		from asn_module.templates.pages.asn_new_services import MAX_BULK_INVOICES

		groups = {"INV-" + str(i): [] for i in range(MAX_BULK_INVOICES + 1)}
		with self.assertRaises(PortalValidationError):
			validate_bulk_group_count(groups)


class TestValidateInvoiceGroupConsistency(FrappeTestCase):
	def _make_bulk_row(self, **overrides):
		defaults = dict(
			row_number=1,
			supplier_invoice_no="INV-1",
			supplier_invoice_date=_test_dates()["supplier_invoice_date"],
			expected_delivery_date=_test_dates()["expected_delivery_date"],
			lr_no="",
			lr_date="",
			transporter_name="",
			vehicle_number="",
			driver_contact="",
			supplier_invoice_amount=100.0,
			purchase_order="PO-001",
			sr_no="1",
			item_code="ITEM-001",
			qty=10.0,
			rate=25.0,
		)
		defaults.update(overrides)
		return ParsedBulkRow(**defaults)

	def test_matching_group_ok(self):
		rows = [
			self._make_bulk_row(row_number=1),
			self._make_bulk_row(row_number=2),
		]
		validate_invoice_group_consistency("INV-1", rows)

	def test_field_mismatch_raises(self):
		rows = [
			self._make_bulk_row(row_number=1, lr_no="LR-001"),
			self._make_bulk_row(row_number=2, lr_no="LR-002"),
		]
		with self.assertRaises(PortalValidationError):
			validate_invoice_group_consistency("INV-1", rows)


class TestValidateInvoiceGroupSinglePurchaseOrder(FrappeTestCase):
	def _make_bulk_row(self, **overrides):
		defaults = dict(
			row_number=1,
			supplier_invoice_no="INV-1",
			supplier_invoice_date=_test_dates()["supplier_invoice_date"],
			expected_delivery_date=_test_dates()["expected_delivery_date"],
			lr_no="",
			lr_date="",
			transporter_name="",
			vehicle_number="",
			driver_contact="",
			supplier_invoice_amount=100.0,
			purchase_order="PO-001",
			sr_no="1",
			item_code="ITEM-001",
			qty=10.0,
			rate=25.0,
		)
		defaults.update(overrides)
		return ParsedBulkRow(**defaults)

	def test_single_purchase_order_group_ok(self):
		rows = [
			self._make_bulk_row(row_number=1, purchase_order="PO-001"),
			self._make_bulk_row(row_number=2, purchase_order="PO-001", sr_no="2"),
		]
		validate_invoice_group_single_purchase_order("INV-1", rows)

	def test_multiple_purchase_orders_in_group_raises(self):
		rows = [
			self._make_bulk_row(row_number=1, purchase_order="PO-001"),
			self._make_bulk_row(row_number=2, purchase_order="PO-002"),
		]
		with self.assertRaises(PortalValidationError) as ctx:
			validate_invoice_group_single_purchase_order("INV-1", rows)
		messages = " ".join(error.get("message", "") for error in ctx.exception.errors)
		self.assertIn("single Purchase Order", messages)


class TestValidateQtyWithinRemaining(FrappeTestCase):
	def test_within_limit_ok(self):
		validate_qty_within_remaining(
			purchase_order_item="POI-001",
			qty=5,
			row_number=1,
			invoice_no="INV-1",
			remaining_qty_by_name={"POI-001": 10},
		)

	def test_exactly_at_limit_ok(self):
		validate_qty_within_remaining(
			purchase_order_item="POI-001",
			qty=10,
			row_number=1,
			invoice_no="INV-1",
			remaining_qty_by_name={"POI-001": 10},
		)

	def test_over_limit_raises(self):
		with self.assertRaises(PortalValidationError):
			validate_qty_within_remaining(
				purchase_order_item="POI-001",
				qty=15,
				row_number=1,
				invoice_no="INV-1",
				remaining_qty_by_name={"POI-001": 10},
			)


class TestValidateSelectedPurchaseOrders(FrappeTestCase):
	def test_empty_list_raises(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_services.get_supplier_open_purchase_orders",
				return_value={},
			),
			self.assertRaises(PortalValidationError),
		):
			validate_selected_purchase_orders(supplier="Supp-001", selected_purchase_orders=[])

	def test_invalid_po_raises(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_services.get_supplier_open_purchase_orders",
				return_value={"PO-0001": SimpleNamespace(name="PO-0001")},
			),
			self.assertRaises(PortalValidationError),
		):
			validate_selected_purchase_orders(
				supplier="Supp-001",
				selected_purchase_orders=["PO-0001", "PO-INVALID"],
			)


def _bulk_fixture():
	"""A real submitted PO plus the supplier, so bulk validation has something to resolve."""
	po = build_purchase_order_with_mandatory_fields(
		create_purchase_order,
		tax_description="_Test ASN Bulk Stock Cap Tax",
	)
	return po, po.supplier, po.items[0]


def _bulk_row(po, po_item, *, row_number, invoice_no, qty):
	return ParsedBulkRow(
		row_number=row_number,
		supplier_invoice_no=invoice_no,
		supplier_invoice_date=_test_dates()["supplier_invoice_date"],
		expected_delivery_date=_test_dates()["expected_delivery_date"],
		lr_no="",
		lr_date="",
		transporter_name="",
		vehicle_number="",
		driver_contact="",
		supplier_invoice_amount=qty * float(po_item.rate or 1),
		purchase_order=po.name,
		sr_no=str(po_item.idx),
		item_code=po_item.item_code,
		qty=qty,
		rate=float(po_item.rate or 1),
	)


class TestBulkUploadStockCap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

	def _breach(self):
		return SimpleNamespace(
			branch="Mumbai",
			item_code="WIDGET",
			row_idxs=(1,),
			on_hand=95.0,
			in_transit=0.0,
			incoming=20.0,
			projected=115.0,
			cap=100.0,
			allowed_qty=5.0,
		)

	def setUp(self):
		self.po, self.supplier, self.po_item = _bulk_fixture()

	def _one_group(self):
		return [_bulk_row(self.po, self.po_item, row_number=1, invoice_no="CAP-INV-1", qty=1)]

	def _two_groups_same_item(self):
		return [
			_bulk_row(self.po, self.po_item, row_number=1, invoice_no="CAP-INV-1", qty=1),
			_bulk_row(self.po, self.po_item, row_number=2, invoice_no="CAP-INV-2", qty=1),
		]

	def test_breach_prevents_any_asn_from_being_created(self):
		inserted = []

		def fake_insert(**kwargs):
			inserted.append(kwargs)
			return SimpleNamespace(name="ASN-TEST")

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
			return_value=([self._breach()], {}),
		):
			with self.assertRaises(PortalValidationError) as ctx:
				create_bulk_asns_for_supplier(
					supplier=self.supplier, rows=self._one_group(), insert_asn=fake_insert
				)

		self.assertEqual(inserted, [])
		messages = " ".join(error.get("message", "") for error in ctx.exception.errors)
		self.assertIn("WIDGET", messages)
		self.assertIn("No ASNs created", messages)

	def test_no_breach_allows_all_asns_to_be_created(self):
		inserted = []

		def fake_insert(**kwargs):
			inserted.append(kwargs)
			return SimpleNamespace(name=f"ASN-{len(inserted)}")

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows", return_value=([], {})
		):
			names = create_bulk_asns_for_supplier(
				supplier=self.supplier, rows=self._one_group(), insert_asn=fake_insert
			)

		self.assertEqual(len(names), len(inserted))
		self.assertTrue(names)

	def test_consumed_headroom_is_carried_across_groups(self):
		seen_consumed = []

		def fake_breaches(payload_rows, exclude_asn_name=None, consumed=None):
			seen_consumed.append(dict(consumed or {}))
			return [], {("Mumbai", self.po_item.item_code): 1.0}

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
			side_effect=fake_breaches,
		):
			create_bulk_asns_for_supplier(
				supplier=self.supplier,
				rows=self._two_groups_same_item(),
				insert_asn=lambda **kwargs: SimpleNamespace(name="ASN-X"),
			)

		self.assertGreaterEqual(len(seen_consumed), 2)
		self.assertEqual(seen_consumed[0], {})
		self.assertEqual(seen_consumed[1], {("Mumbai", self.po_item.item_code): 1.0})

	def test_breaching_group_does_not_contribute_headroom_to_later_group(self):
		"""A group that produces a breach must not have its ``accepted`` folded into
		``consumed`` for the next group.

		``accepted`` is evaluate()'s record of every filtered group's incoming quantity,
		whether or not that particular group breached -- see evaluate()'s docstring. The
		bulk loop must still only fold a group's ``accepted`` into ``consumed`` when that
		group came back breach-free (mirrored here by returning a non-empty ``accepted``
		alongside a breach for the first group). If it folded accepted in regardless, a
		later group referencing the same item would be evaluated against inflated headroom
		it never earned, and could be spuriously blamed for a breach that the earlier
		(rejected) group actually caused.
		"""
		seen_consumed = []

		def fake_breaches(payload_rows, exclude_asn_name=None, consumed=None):
			seen_consumed.append(dict(consumed or {}))
			if len(seen_consumed) == 1:
				return [self._breach()], {("Mumbai", self.po_item.item_code): 1.0}
			return [], {}

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
			side_effect=fake_breaches,
		):
			with self.assertRaises(PortalValidationError):
				create_bulk_asns_for_supplier(
					supplier=self.supplier,
					rows=self._two_groups_same_item(),
					insert_asn=lambda **kwargs: SimpleNamespace(name="ASN-X"),
				)

		self.assertEqual(len(seen_consumed), 2)
		self.assertEqual(seen_consumed[0], {})
		self.assertEqual(
			seen_consumed[1],
			{},
			"the second group must not see headroom claimed by the first group's breaching rows",
		)


def _bulk_cap_warehouse(name: str, *, company: str) -> str:
	"""A second real Warehouse under ``company``, distinct from the one
	build_purchase_order_with_mandatory_fields would otherwise default to, so a test can
	control which one is a branch's registered cap warehouse and which one is not.

	``company`` must be the same company create_purchase_order() resolves to (its default
	is not necessarily whichever Company happens to sort first on this site) -- Purchase
	Order validation rejects a warehouse under a different company outright.
	"""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full_name = f"{name} - {abbr}"
	if not frappe.db.exists("Warehouse", full_name):
		frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": name, "company": company, "is_group": 0}
		).insert(ignore_permissions=True)
	return full_name


class TestBulkUploadStockCapRealPipeline(FrappeTestCase):
	"""Exercises create_bulk_asns_for_supplier end to end against the real evaluate()/
	fetch_cap_context() layer, without mocking breaches_for_asn_rows.

	TestBulkUploadStockCap above mocks the cap check out entirely, so it cannot see bugs
	in the plumbing between the bulk loop and the real cap-checking layer -- which is
	exactly where both regressions covered here lived: the bulk loop crediting headroom
	for a line the evaluator itself would have ignored, and a breach citing a synthetic
	per-group position instead of the row's real CSV line number.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

	def setUp(self):
		self.branch = "_Test Bulk Real Cap Branch"
		if not frappe.db.exists("Branch", self.branch):
			frappe.get_doc({"doctype": "Branch", "branch": self.branch}).insert(ignore_permissions=True)

		self.item_code = "_Test Bulk Real Cap Item"
		if not frappe.db.exists("Item", self.item_code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": self.item_code,
					"item_name": self.item_code,
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				}
			).insert(ignore_permissions=True)
		frappe.db.delete("ASN Item Branch Cap", {"item": self.item_code})
		frappe.get_doc(
			{
				"doctype": "ASN Item Branch Cap",
				"branch": self.branch,
				"item": self.item_code,
				"max_qty": 100,
			}
		).insert(ignore_permissions=True)

		# FrappeTestCase only rolls back once at class teardown, not per test.
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")

		# Both warehouses are created explicitly, under the same company
		# create_purchase_order() itself defaults to -- rather than letting one of them
		# come from create_purchase_order's own "first Warehouse for this company"
		# fallback (_ensure_warehouse()). That fallback has no explicit ordering, and once
		# this class's own custom warehouse exists in the same uncommitted transaction, it
		# can just as easily be the one that sorts first on a later test in this class --
		# silently collapsing "cap" and "non-cap" onto the very same warehouse.
		company = _resolve_test_company()
		self.cap_warehouse = _bulk_cap_warehouse("_Test Bulk Real Cap WH", company=company)
		self.non_cap_warehouse = _bulk_cap_warehouse("_Test Bulk Real NonCap WH", company=company)

		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": self.branch,
				"enabled": 1,
				"warehouses": [{"warehouse": self.cap_warehouse}],
			}
		).insert(ignore_permissions=True)

	def _po(self, *, warehouse, qty):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Bulk Real Cap Tax",
			item_code=self.item_code,
			warehouse=warehouse,
			qty=qty,
		)
		frappe.db.set_value("Purchase Order", po.name, "branch", self.branch)
		return po

	def test_line_in_non_cap_warehouse_does_not_consume_headroom_from_later_group(self):
		"""Reproduces the finding precisely: an earlier invoice group's line lands in a
		warehouse outside the branch's cap-warehouse list -- invisible to the rule -- and
		must not consume headroom that a later group in the same upload actually needs.

		Pre-fix, consumed_from_breach_free_rows summed every line of the first group
		(including the one in the non-cap warehouse) with none of evaluate()'s filters
		applied, so the second group's 50 units were wrongly evaluated against 90 units of
		phantom headroom (90 + 50 = 140 > the cap of 100) and the whole upload was
		rejected. This test fails against that code and passes once the bulk loop carries
		forward evaluate()'s own ``accepted`` dict instead.
		"""
		po_non_cap = self._po(warehouse=self.non_cap_warehouse, qty=90)
		po_cap = self._po(warehouse=self.cap_warehouse, qty=50)
		self.assertEqual(po_non_cap.supplier, po_cap.supplier)

		rows = [
			_bulk_row(po_non_cap, po_non_cap.items[0], row_number=2, invoice_no="REAL-CAP-INV-1", qty=90),
			_bulk_row(po_cap, po_cap.items[0], row_number=3, invoice_no="REAL-CAP-INV-2", qty=50),
		]

		names = create_bulk_asns_for_supplier(
			supplier=po_non_cap.supplier,
			rows=rows,
			insert_asn=lambda **kwargs: SimpleNamespace(
				name=f"ASN-REAL-{kwargs['header']['supplier_invoice_no']}"
			),
		)

		self.assertEqual(len(names), 2)

	def test_breach_error_reports_the_real_csv_row_number(self):
		"""The reported row number must be the CSV row (ParsedBulkRow.row_number), not a
		position within this invoice group. Pre-fix, _collect_stock_cap_errors built its
		cap-check rows via ``enumerate(items, start=1)``, which restarts at 1 for every
		invoice group regardless of where its rows actually sat in the uploaded CSV, and
		omitted ``row_number=`` on the error_entry call entirely. This test fails against
		that code (row_number is None, or the group-relative 1) and passes once the real
		CSV row_number is threaded through.
		"""
		po = self._po(warehouse=self.cap_warehouse, qty=1000)
		row = _bulk_row(po, po.items[0], row_number=9, invoice_no="REAL-CAP-INV-ROWNUM", qty=150)

		with self.assertRaises(PortalValidationError) as ctx:
			create_bulk_asns_for_supplier(
				supplier=po.supplier,
				rows=[row],
				insert_asn=lambda **kwargs: SimpleNamespace(name="ASN-REAL-ROWNUM"),
			)

		row_numbers = [error.get("row_number") for error in ctx.exception.errors]
		self.assertIn(9, row_numbers)
		self.assertNotIn(1, row_numbers)
