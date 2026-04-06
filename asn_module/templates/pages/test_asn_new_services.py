from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
	enforce_bulk_limits,
	normalize_group_field,
	normalize_group_value,
	parse_non_negative_rate,
	parse_optional_non_negative_rate,
	parse_positive_qty,
	parse_required_supplier_invoice_amount,
	validate_bulk_group_count,
	validate_invoice_group_consistency,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
)


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
			supplier_invoice_date="2026-04-05",
			expected_delivery_date="2026-04-06",
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
