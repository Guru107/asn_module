from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
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
