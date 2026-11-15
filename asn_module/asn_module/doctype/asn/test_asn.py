import json
from contextlib import contextmanager
from html import unescape
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate, today

from asn_module.asn_module.doctype.asn.asn import (
	get_item_transition_summary,
	get_po_items,
	get_purchase_order_items,
)
from asn_module.handlers.utils import fill_custom_fiscal_year
from asn_module.qr_engine.scan_codes import normalize_scan_code
from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
	create_bulk_asns_for_supplier,
	fetch_purchase_order_items,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates
from asn_module.utils.test_setup import (
	TEST_COMPANY_NAME,
	apply_item_site_requirements,
	apply_receipt_site_requirements,
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
	ensure_leaf_supplier_group,
	make_test_breach,
	message_log_text,
	reset_test_item_stock_flags,
)

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Currency",
	"Item",
	"Item Group",
	"Purchase Order",
	"Purchase Order Item",
	"Supplier",
	"Supplier Group",
	"UOM",
	"Warehouse",
]


def _first_or_none(doctype, filters=None):
	names = frappe.get_all(doctype, filters=filters or {}, pluck="name", limit=1)
	return names[0] if names else None


def _resolve_test_company():
	company = TEST_COMPANY_NAME if frappe.db.exists("Company", TEST_COMPANY_NAME) else None
	if not company:
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		if default_company and frappe.db.exists("Company", default_company):
			company = default_company
	if not company:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		raise AssertionError("No Company records exist in the test site")
	return company


def _ensure_supplier():
	supplier_name = "_Test ASN Supplier"
	if frappe.db.exists("Supplier", supplier_name):
		return supplier_name

	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": supplier_name,
			"supplier_type": "Company",
			"supplier_group": ensure_leaf_supplier_group(),
		}
	)
	supplier.insert(ignore_permissions=True)
	return supplier.name


def _ensure_other_supplier():
	supplier_name = "_Test ASN Other Supplier"
	if frappe.db.exists("Supplier", supplier_name):
		return supplier_name

	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": supplier_name,
			"supplier_type": "Company",
			"supplier_group": ensure_leaf_supplier_group(),
		}
	)
	supplier.insert(ignore_permissions=True)
	return supplier.name


def _other_uom(uom: str) -> str:
	return frappe.get_all("UOM", filters={"name": ["!=", uom]}, pluck="name", limit=1)[0]


def _ensure_item(item_code: str = "_Test ASN Item") -> str:
	if frappe.db.exists("Item", item_code):
		# Keep the default ASN test item non-inspection to avoid cross-test leakage
		# from stock-transfer/QI tests that temporarily enable inspection.
		current_value = frappe.db.get_value("Item", item_code, "inspection_required_before_purchase")
		if current_value:
			frappe.db.set_value(
				"Item",
				item_code,
				"inspection_required_before_purchase",
				0,
				update_modified=False,
			)
		# Site imports can leave serial/batch flags on the persistent test item.
		reset_test_item_stock_flags(item_code)
		return item_code

	item_group = _first_or_none("Item Group") or "All Item Groups"
	uom = _first_or_none("UOM") or "Nos"
	item_doc = {
		"doctype": "Item",
		"item_code": item_code,
		"item_name": item_code,
		"item_group": item_group,
		"stock_uom": uom,
		"inspection_required_before_purchase": 0,
	}
	item = frappe.get_doc(item_doc)
	apply_item_site_requirements(item)
	item.insert(ignore_permissions=True)
	return item.name


def _ensure_company():
	return _resolve_test_company()


def _ensure_currency():
	currency = frappe.get_cached_value("Company", _ensure_company(), "default_currency")
	if currency:
		return currency

	currency = _first_or_none("Currency")
	if not currency:
		raise AssertionError("No Currency records exist in the test site")
	return currency


def _ensure_uom():
	uom = _first_or_none("UOM")
	if not uom:
		raise AssertionError("No UOM records exist in the test site")
	return uom


def _ensure_warehouse():
	warehouse = _first_or_none("Warehouse", filters={"company": _ensure_company()})
	if not warehouse:
		raise AssertionError("No Warehouse records exist in the test site")
	return warehouse


def _is_in_active_fiscal_year(date_value: str) -> bool:
	return bool(
		frappe.db.exists(
			"Fiscal Year",
			{
				"disabled": 0,
				"year_start_date": ("<=", date_value),
				"year_end_date": (">=", date_value),
			},
		)
	)


def _normalize_po_dates_for_active_fiscal_year(
	transaction_date: str, schedule_date: str, item_schedule_date: str
) -> tuple[str, str, str]:
	normalized_transaction_date = (
		transaction_date if _is_in_active_fiscal_year(transaction_date) else nowdate()
	)
	normalized_schedule_date = schedule_date
	if not _is_in_active_fiscal_year(normalized_schedule_date):
		normalized_schedule_date = add_days(normalized_transaction_date, 1)
	if normalized_schedule_date < normalized_transaction_date:
		normalized_schedule_date = normalized_transaction_date

	normalized_item_schedule_date = item_schedule_date
	if not _is_in_active_fiscal_year(normalized_item_schedule_date):
		normalized_item_schedule_date = add_days(normalized_transaction_date, 1)
	if normalized_item_schedule_date < normalized_transaction_date:
		normalized_item_schedule_date = normalized_transaction_date

	return (
		normalized_transaction_date,
		normalized_schedule_date,
		normalized_item_schedule_date,
	)


def make_test_asn(*, purchase_order=None, supplier=None, supplier_invoice_no=None, qty=1):
	po = purchase_order or create_purchase_order()
	po_item = po.items[0]

	return frappe.get_doc(
		{
			"doctype": "ASN",
			"supplier": supplier or po.supplier,
			"supplier_invoice_no": supplier_invoice_no or f"INV-{frappe.generate_hash(length=8)}",
			"supplier_invoice_date": today(),
			"expected_delivery_date": today(),
			"supplier_invoice_amount": flt(qty) * flt(po_item.rate),
			"vehicle_number": "MH12AB1234",
			"items": [
				{
					"purchase_order": po.name,
					"purchase_order_item": po_item.name,
					"item_code": po_item.item_code,
					"qty": qty,
					"uom": po_item.uom,
					"rate": po_item.rate,
				}
			],
		}
	)


def make_test_asn_with_two_items(*, purchase_order=None, supplier=None, supplier_invoice_no=None, qty=5):
	asn = make_test_asn(
		purchase_order=purchase_order,
		supplier=supplier,
		supplier_invoice_no=supplier_invoice_no,
		qty=qty,
	)
	first_item = asn.items[0]
	asn.append(
		"items",
		{
			"purchase_order": first_item.purchase_order,
			"purchase_order_item": first_item.purchase_order_item,
			"item_code": first_item.item_code,
			"qty": qty,
			"uom": first_item.uom,
			"rate": first_item.rate,
		},
	)
	return asn


@contextmanager
def _over_receipt_allowance(*, item_code: str, item_allowance, stock_allowance, role=None):
	"""Set the Item and Stock Settings allowances for one assertion, then put them back.

	A zero Item allowance is what ERPNext treats as unset.
	"""
	previous_item = frappe.db.get_value("Item", item_code, "over_delivery_receipt_allowance")
	previous_stock = frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance")
	previous_role = frappe.db.get_single_value("Stock Settings", "role_allowed_to_over_deliver_receive")
	frappe.db.set_value(
		"Item", item_code, "over_delivery_receipt_allowance", item_allowance, update_modified=False
	)
	frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", stock_allowance)
	if role is not None:
		frappe.db.set_single_value("Stock Settings", "role_allowed_to_over_deliver_receive", role)
	frappe.clear_cache(doctype="Item")
	try:
		yield
	finally:
		frappe.db.set_value(
			"Item", item_code, "over_delivery_receipt_allowance", previous_item, update_modified=False
		)
		frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", previous_stock)
		frappe.db.set_single_value("Stock Settings", "role_allowed_to_over_deliver_receive", previous_role)
		frappe.clear_cache(doctype="Item")


def create_purchase_order(**kwargs):
	company = kwargs.get("company") or _ensure_company()
	supplier = kwargs.get("supplier") or _ensure_supplier()
	item_code = kwargs.get("item_code") or _ensure_item()
	currency = (
		kwargs.get("currency")
		or frappe.get_cached_value("Company", company, "default_currency")
		or _ensure_currency()
	)
	warehouse = kwargs.get("warehouse") or _ensure_warehouse()
	transaction_date = kwargs.get("transaction_date", nowdate())
	schedule_date = kwargs.get("schedule_date", add_days(nowdate(), 1))
	item_schedule_date = kwargs.get("item_schedule_date", add_days(nowdate(), 1))
	(
		transaction_date,
		schedule_date,
		item_schedule_date,
	) = _normalize_po_dates_for_active_fiscal_year(
		transaction_date=transaction_date,
		schedule_date=schedule_date,
		item_schedule_date=item_schedule_date,
	)

	po = frappe.new_doc("Purchase Order")
	po.transaction_date = transaction_date
	po.schedule_date = schedule_date
	po.company = company
	po.supplier = supplier
	po.is_subcontracted = kwargs.get("is_subcontracted", 0)
	po.currency = currency
	po.conversion_factor = kwargs.get("conversion_factor", 1)
	po.supplier_warehouse = kwargs.get("supplier_warehouse")
	item_count = max(int(kwargs.get("item_count", 1) or 1), 1)
	use_unique_items = bool(kwargs.get("unique_items")) and not kwargs.get("item_code")
	for idx in range(item_count):
		row_item_code = _ensure_item(f"_Test ASN Item {idx + 1}") if use_unique_items else item_code
		po.append(
			"items",
			{
				"item_code": row_item_code,
				"warehouse": warehouse,
				"qty": kwargs.get("qty", 10),
				"rate": kwargs.get("rate", 500),
				"schedule_date": item_schedule_date,
				"include_exploded_items": kwargs.get("include_exploded_items", 1),
			},
		)
	po.set_missing_values()

	if not kwargs.get("do_not_save"):
		from asn_module.utils.test_setup import apply_purchase_order_site_requirements

		apply_purchase_order_site_requirements(po, tax_description="_Test ASN Purchase Order Tax")
		po.insert(ignore_permissions=True)
		if not kwargs.get("do_not_submit"):
			po.submit()

	return po


def create_purchase_order_with_fiscal_dates(**kwargs):
	"""Create a Purchase Order seeded with fiscal-year-safe baseline dates."""
	if any(kwargs.get(key) is None for key in ("transaction_date", "schedule_date", "item_schedule_date")):
		from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates

		dates = get_fiscal_year_test_dates()
		kwargs.setdefault("transaction_date", dates["transaction_date"])
		kwargs.setdefault("schedule_date", dates["schedule_date"])
		kwargs.setdefault("item_schedule_date", dates["item_schedule_date"])
	return create_purchase_order(**kwargs)


class TestASN(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def test_insert_rejects_a_row_whose_order_belongs_to_another_supplier(self):
		asn = make_test_asn(supplier=_ensure_other_supplier())

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("Row 1: Supplier _Test ASN Other Supplier does not match", str(raised.exception))

	def test_insert_rejects_a_line_that_belongs_to_another_purchase_order(self):
		other_order = create_purchase_order()
		asn = make_test_asn()
		asn.items[0].purchase_order_item = other_order.items[0].name

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: Purchase Order line {other_order.items[0].name} belongs to {other_order.name}, not",
			str(raised.exception),
		)

	def test_insert_rejects_an_item_that_differs_from_the_order_line(self):
		asn = make_test_asn()
		line_item = asn.items[0].item_code
		asn.items[0].item_code = _ensure_item("_Test ASN Item 2")

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(f"Row 1: Item Code _Test ASN Item 2 does not match {line_item}", str(raised.exception))

	def test_insert_rejects_a_uom_that_differs_from_the_order_line(self):
		asn = make_test_asn()
		line_uom = asn.items[0].uom
		wrong_uom = _other_uom(line_uom)
		asn.items[0].uom = wrong_uom

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(f"Row 1: UOM {wrong_uom} does not match {line_uom}", str(raised.exception))

	def test_insert_rejects_a_line_of_a_cancelled_purchase_order(self):
		purchase_order = create_purchase_order()
		asn = make_test_asn(purchase_order=purchase_order)
		purchase_order.cancel()

		# Frappe's link check refuses a cancelled order before validate runs.
		with self.assertRaises(frappe.CancelledLinkError):
			asn.insert(ignore_permissions=True)

	def test_insert_rejects_a_line_of_a_draft_purchase_order(self):
		purchase_order = create_purchase_order(do_not_submit=True)
		asn = make_test_asn(purchase_order=purchase_order)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: Purchase Order {purchase_order.name} is Draft, not open", str(raised.exception)
		)

	def test_insert_rejects_a_line_of_a_closed_purchase_order(self):
		purchase_order = create_purchase_order()
		frappe.db.set_value("Purchase Order", purchase_order.name, "status", "Closed", update_modified=False)
		# Zero qty keeps the remaining-qty check, which already refuses shipping, out of the way.
		asn = make_test_asn(purchase_order=purchase_order, qty=0)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: Purchase Order {purchase_order.name} is Closed, not open", str(raised.exception)
		)

	def test_insert_rejects_empty_items(self):
		asn = make_test_asn()
		asn.set("items", [])

		with self.assertRaises(frappe.ValidationError):
			asn.insert(ignore_permissions=True)

	def test_insert_rejects_blank_vehicle_number(self):
		asn = make_test_asn()
		asn.vehicle_number = ""

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("Vehicle Number is required", str(raised.exception))

	def test_insert_saves_when_vehicle_number_is_present(self):
		asn = make_test_asn()
		asn.vehicle_number = "MH12AB1234"

		doc = asn.insert(ignore_permissions=True)

		self.assertEqual(doc.vehicle_number, "MH12AB1234")
		self.assertTrue(doc.name)

	def test_draft_insert_allows_non_positive_qty_and_submit_rejects_it(self):
		asn = make_test_asn(qty=0)
		asn.insert(ignore_permissions=True)
		self.assertEqual(asn.docstatus, 0)

		with self.assertRaises(frappe.ValidationError):
			asn.submit()

	def test_insert_rejects_duplicate_supplier_invoice_for_active_docs(self):
		invoice_no = f"INV-{frappe.generate_hash(length=8)}"
		first = make_test_asn(supplier_invoice_no=invoice_no)
		first.insert(ignore_permissions=True)

		duplicate = make_test_asn(supplier_invoice_no=invoice_no)

		with self.assertRaises(frappe.ValidationError):
			duplicate.insert(ignore_permissions=True)

	def test_insert_allows_duplicate_supplier_invoice_after_cancel(self):
		invoice_no = f"INV-{frappe.generate_hash(length=8)}"
		doc = make_test_asn(supplier_invoice_no=invoice_no)
		doc.insert(ignore_permissions=True)

		doc.submit()

		doc.cancel()

		duplicate = make_test_asn(supplier_invoice_no=invoice_no)
		duplicate.insert(ignore_permissions=True)

	def test_insert_rejects_shipped_qty_above_remaining_po_qty(self):
		po = create_purchase_order(qty=10)
		existing = make_test_asn(purchase_order=po, qty=7)
		existing.insert(ignore_permissions=True)

		over_limit = make_test_asn(purchase_order=po, qty=4)

		with self.assertRaises(frappe.ValidationError):
			over_limit.insert(ignore_permissions=True)

	def test_insert_allows_duplicate_po_item_rows_within_remaining_po_qty(self):
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=4)
		po_item = po.items[0]
		asn.append(
			"items",
			{
				"purchase_order": po.name,
				"purchase_order_item": po_item.name,
				"item_code": po_item.item_code,
				"qty": 5,
				"uom": po_item.uom,
				"rate": po_item.rate,
			},
		)

		asn.insert(ignore_permissions=True)

	def test_insert_rejects_aggregate_po_qty_across_active_asns_and_duplicate_rows(self):
		po = create_purchase_order(qty=10)
		existing = make_test_asn(purchase_order=po, qty=6)
		existing.insert(ignore_permissions=True)

		asn = make_test_asn(purchase_order=po, qty=3)
		po_item = po.items[0]
		asn.append(
			"items",
			{
				"purchase_order": po.name,
				"purchase_order_item": po_item.name,
				"item_code": po_item.item_code,
				"qty": 2,
				"uom": po_item.uom,
				"rate": po_item.rate,
			},
		)

		with self.assertRaises(frappe.ValidationError):
			asn.insert(ignore_permissions=True)

	def test_validate_leaves_a_blank_supplier_invoice_amount(self):
		po = create_purchase_order(qty=2, rate=100)
		asn = make_test_asn(purchase_order=po, qty=2)
		asn.supplier_invoice_amount = 0
		self.assertEqual(frappe.utils.flt(asn.supplier_invoice_amount), 0)
		asn.validate()
		self.assertEqual(frappe.utils.flt(asn.supplier_invoice_amount), 0)

	def test_validate_preserves_a_typed_supplier_invoice_amount(self):
		po = create_purchase_order(qty=2, rate=100)
		asn = make_test_asn(purchase_order=po, qty=2)
		asn.supplier_invoice_amount = 250
		asn.validate()
		self.assertEqual(frappe.utils.flt(asn.supplier_invoice_amount), 250)

	def test_insert_defaults_status_to_draft(self):
		asn = make_test_asn()
		doc = asn.insert(ignore_permissions=True)

		self.assertEqual(doc.status, "Draft")

	def test_get_context_sets_website_fields_and_portal_actions(self):
		asn = make_test_asn()
		asn.name = "ASN-CONTEXT-001"
		context = SimpleNamespace()
		with (
			patch(
				"asn_module.asn_module.doctype.asn.asn.asn_eligible_for_supplier_portal_cancel",
				return_value=True,
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn.asn_eligible_for_supplier_portal_delete",
				return_value=False,
			),
		):
			asn.get_context(context)

		self.assertEqual(context.doc, asn)
		self.assertEqual(context.title, "ASN-CONTEXT-001")
		self.assertTrue(context.can_cancel_portal)
		self.assertFalse(context.can_delete_portal)

	def test_make_route_keeps_detail_pages_under_asn_prefix(self):
		asn = frappe.get_doc({"doctype": "ASN", "name": "ASN-0002"})
		self.assertEqual(asn.make_route(), "asn/asn-0002")

	def test_purge_scan_codes_noops_when_doctype_missing(self):
		asn = make_test_asn()
		asn.name = "ASN-NO-SCAN-CODE"
		with (
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.exists", return_value=False),
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.delete") as mock_delete,
		):
			asn._purge_scan_codes_for_asn()

		mock_delete.assert_not_called()

	def test_delete_asn_transition_logs_noops_when_doctype_missing(self):
		asn = make_test_asn()
		asn.name = "ASN-NO-LOG"
		with (
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.exists", return_value=False),
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.delete") as mock_delete,
		):
			asn._delete_asn_transition_logs()

		mock_delete.assert_not_called()

	def test_delete_linked_draft_purchase_receipts_noops_without_asn_column(self):
		asn = make_test_asn()
		with (
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.has_column", return_value=False),
			patch("asn_module.asn_module.doctype.asn.asn.frappe.get_all") as get_all,
		):
			asn._delete_linked_draft_purchase_receipts()

		get_all.assert_not_called()

	def test_validate_supplier_invoice_unique_ignores_blank_invoice_no(self):
		asn = make_test_asn()
		asn.supplier_invoice_no = ""
		with patch("asn_module.asn_module.doctype.asn.asn.frappe.db.exists") as exists:
			asn._validate_supplier_invoice_unique()

		exists.assert_not_called()

	def test_validate_po_qty_ignores_rows_without_po_links(self):
		asn = make_test_asn()
		asn.items[0].purchase_order = ""
		asn.items[0].purchase_order_item = ""
		with patch("asn_module.asn_module.doctype.asn.asn.frappe.get_all") as get_all:
			asn._validate_po_qty()

		get_all.assert_not_called()

	def test_save_refuses_shipped_qty_when_ordered_qty_is_zero(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Zero Ordered Qty Tax",
			qty=10,
		)
		frappe.db.set_value("Purchase Order Item", po.items[0].name, "qty", 0)

		with self.assertRaises(frappe.ValidationError) as raised:
			make_test_asn(purchase_order=po, qty=1).insert(ignore_permissions=True)

		self.assertIn("Shipped qty 1.0 exceeds remaining PO qty 0", str(raised.exception))

	def test_save_refuses_shipped_qty_when_the_purchase_order_item_is_missing(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Missing PO Item Tax",
			qty=10,
		)
		asn = make_test_asn(purchase_order=po, qty=1)
		asn.items[0].purchase_order_item = "POI-MISSING"

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("Shipped qty 1.0 exceeds remaining PO qty 0", str(raised.exception))

	def test_submit_sets_status_date_and_scan_code_label_without_image_files(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)
		asn.submit()
		asn.reload()

		self.assertEqual(asn.status, "Submitted")
		self.assertEqual(str(asn.asn_date), today())
		self.assertEqual(normalize_scan_code(asn.scan_code_label), asn.scan_code_label)
		self.assertTrue(frappe.db.exists("Scan Code", asn.scan_code_label))
		self.assertFalse(
			frappe.db.exists("File", {"attached_to_doctype": "ASN", "attached_to_name": asn.name})
		)
		self.assertFalse(frappe.get_meta("ASN").has_field("qr_code"))
		self.assertFalse(frappe.get_meta("ASN").has_field("barcode"))

	def test_print_format_draws_both_images_from_the_scan_code_label(self):
		frappe.reload_doc("asn_module", "print_format", "asn_scan_codes")
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)
		asn.submit()
		asn.reload()

		html = unescape(frappe.get_print("ASN", asn.name, print_format="ASN Scan Codes"))

		url = f"/api/method/asn_module.qr_engine.generate.scan_image?code={asn.scan_code_label}"
		self.assertIn(f"{url}&kind=qr", html)
		self.assertIn(f"{url}&kind=barcode", html)

	def test_cancel_sets_status_cancelled(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		asn.submit()

		asn.cancel()
		asn.reload()

		self.assertEqual(asn.status, "Cancelled")

	def test_cancel_removes_scan_code_registry_rows(self):
		if not frappe.db.exists("DocType", "Scan Code"):
			return

		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		asn.submit()

		asn.reload()
		linked = frappe.get_all(
			"Scan Code",
			filters={"source_doctype": "ASN", "source_name": asn.name},
			pluck="name",
		)
		self.assertGreaterEqual(len(linked), 1)

		asn.cancel()

		remaining = frappe.get_all(
			"Scan Code",
			filters={"source_doctype": "ASN", "source_name": asn.name},
			pluck="name",
		)
		self.assertEqual(remaining, [])

	def test_delete_cancelled_asn_when_no_purchase_receipt_linked(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		asn.submit()

		asn.cancel()
		name = asn.name
		frappe.delete_doc("ASN", name)

		self.assertFalse(frappe.db.exists("ASN", name))

	def test_on_trash_raises_when_purchase_receipt_still_linked(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with (
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.db.get_value",
				return_value="PR-TEST-001",
			),
		):
			with self.assertRaises(frappe.LinkExistsError):
				asn.on_trash()

	def test_on_trash_deletes_asn_transition_log_rows(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with (
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.db.exists",
				return_value=True,
			),
			patch("asn_module.asn_module.doctype.asn.asn.frappe.db.delete") as mock_delete,
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.db.has_column",
				return_value=False,
			),
		):
			asn.on_trash()

		self.assertEqual(mock_delete.call_count, 1)
		mock_delete.assert_called_once_with("ASN Transition Log", {"asn": asn.name})

	def test_before_cancel_deletes_linked_draft_purchase_receipts(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		asn.submit()

		with (
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"asn_module.asn_module.doctype.asn.asn.frappe.get_all",
				return_value=["PR-DRAFT-1"],
			),
			patch("asn_module.asn_module.doctype.asn.asn.frappe.delete_doc") as mock_delete,
		):
			asn.cancel()

		mock_delete.assert_called_once_with("Purchase Receipt", "PR-DRAFT-1")

	def _set_received_qty_in_db(self, asn, *received):
		# Handlers write received_qty in SQL; update_receipt_status must read it from there.
		for item, qty in zip(asn.items, received, strict=True):
			frappe.db.set_value("ASN Item", item.name, "received_qty", qty, update_modified=False)

	def test_update_receipt_status_keeps_received_qty_written_after_doc_was_loaded(self):
		# Regression #120: a stale in-memory doc must not overwrite another receipt's increment.
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)
		asn.submit()
		stale = frappe.get_doc("ASN", asn.name)

		self._set_received_qty_in_db(asn, 5, 5)
		stale.update_receipt_status()

		self.assertEqual(
			frappe.get_all("ASN Item", {"parent": asn.name}, pluck="received_qty", order_by="idx"),
			[5, 5],
		)
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Received")

	def test_update_receipt_status_closes_short_receipt_and_updates_discrepancy_qty(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		self._set_received_qty_in_db(asn, 2, 5)

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.status, "Closed")
		self.assertEqual(asn.items[0].received_qty, 2)
		self.assertEqual(asn.items[1].received_qty, 5)
		self.assertEqual(asn.items[0].discrepancy_qty, 3)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_update_receipt_status_sets_received_when_all_items_fully_received(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		self._set_received_qty_in_db(asn, 5, 5)

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].discrepancy_qty, 0)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_update_receipt_status_works_for_submitted_asn(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		asn.submit()

		asn.reload()
		self._set_received_qty_in_db(asn, 2, 5)

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.docstatus, 1)
		self.assertEqual(asn.status, "Closed")
		self.assertEqual(asn.items[0].received_qty, 2)
		self.assertEqual(asn.items[1].received_qty, 5)
		self.assertEqual(asn.items[0].discrepancy_qty, 3)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_update_receipt_status_reopens_closed_asn_when_receipt_is_reversed(self):
		# Cancelling the receipt reverses received_qty; the ASN must go back in transit.
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)
		asn.submit()
		self._set_received_qty_in_db(asn, 2, 5)
		asn.update_receipt_status()
		self.assertEqual(asn.status, "Closed")

		self._set_received_qty_in_db(asn, 0, 0)
		asn.update_receipt_status()

		self.assertEqual(asn.status, "Submitted")

	def test_amendment_resets_copied_lifecycle_fields(self):
		frappe.reload_doc("asn_module", "doctype", "asn")

		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		asn.submit()

		asn.cancel()

		amended = frappe.copy_doc(asn, ignore_no_copy=False)
		amended.amended_from = asn.name
		amended.docstatus = 0

		self.assertIsNone(amended.status)
		self.assertIsNone(amended.asn_date)
		self.assertIsNone(amended.scan_code_label)

		amended.insert(ignore_permissions=True)

		self.assertEqual(amended.status, "Draft")
		self.assertEqual(amended.amended_from, asn.name)

	def test_get_purchase_order_items_returns_only_remaining_quantities(self):
		po = create_purchase_order(qty=10)
		existing = make_test_asn(purchase_order=po, qty=6)
		existing.insert(ignore_permissions=True)

		items = get_purchase_order_items(po.name)

		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["purchase_order"], po.name)
		self.assertEqual(items[0]["purchase_order_item"], po.items[0].name)
		self.assertEqual(items[0]["qty"], 4)

	def test_desk_and_portal_offer_the_same_remaining_qty_ignoring_cancelled_asns(self):
		"""Ordered 10, 4 still shipped, 9 withdrawn. Both doors offer 6, and 7 is refused."""
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Remaining Qty Tax",
			qty=10,
		)
		withdrawn = make_test_asn(purchase_order=po, qty=9)
		withdrawn.insert(ignore_permissions=True)
		withdrawn.submit()
		withdrawn.cancel()
		shipped = make_test_asn(purchase_order=po, qty=4)
		shipped.insert(ignore_permissions=True)

		offered = get_purchase_order_items(po.name)
		_rows, remaining = fetch_purchase_order_items([po.name])

		self.assertEqual(len(offered), 1)
		self.assertEqual(offered[0]["qty"], 6)
		self.assertEqual(remaining[po.items[0].name], 6)

	def test_desk_hides_a_line_when_remaining_qty_is_zero_and_portal_reports_zero(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Remaining Qty Tax",
			qty=10,
		)
		make_test_asn(purchase_order=po, qty=10).insert(ignore_permissions=True)

		self.assertEqual(get_purchase_order_items(po.name), [])

		_rows, remaining = fetch_purchase_order_items([po.name])
		self.assertEqual(remaining[po.items[0].name], 0)

	def test_get_po_items_filters_results_by_purchase_order_and_search_text(self):
		po = create_purchase_order(item_code=_ensure_item())

		results = get_po_items(
			"ASN Item",
			"_Test ASN",
			"item_code",
			0,
			20,
			{"purchase_order": po.name},
		)

		self.assertGreaterEqual(len(results), 1)
		self.assertEqual(results[0][0], po.items[0].item_code)

	def test_get_po_items_returns_empty_without_purchase_order_filter(self):
		self.assertEqual(get_po_items("ASN Item", "test", "item_code", 0, 20, {}), [])

	def test_get_purchase_order_items_rejects_inaccessible_purchase_order(self):
		with patch(
			"asn_module.asn_module.doctype.asn.asn._get_accessible_purchase_order",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				get_purchase_order_items("PO-0001")

	def test_get_po_items_rejects_inaccessible_purchase_order(self):
		with patch(
			"asn_module.asn_module.doctype.asn.asn._get_accessible_purchase_order",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				get_po_items("ASN Item", "test", "item_code", 0, 20, {"purchase_order": "PO-0001"})

	def test_get_item_transition_summary_rejects_without_read_permission(self):
		doc = SimpleNamespace(has_permission=lambda _ptype: False)
		with (
			patch("asn_module.asn_module.doctype.asn.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.PermissionError),
		):
			get_item_transition_summary("ASN-0001")


class TestRemainingQtyAfterReturn(FrappeTestCase):
	"""A return frees further Shipped Qty on the same Purchase Order line.

	The seam is saving an ASN, plus the quantity the desk picker, the supplier
	portal, and a bulk upload offer. Remaining Qty includes the over-receipt allowance.
	"""

	@classmethod
	def setUpClass(cls):
		before_tests()
		disable_hsn_validation()
		super().setUpClass()
		# The portal search lists at most 200 open POs per supplier; the shared
		# "_Test ASN Supplier" accrues committed residue on dev sites, drowning a
		# test's own PO. Isolate the class on its own supplier.
		supplier_name = "_Test ASN Remaining Qty Supplier"
		if not frappe.db.exists("Supplier", supplier_name):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": supplier_name,
					"supplier_type": "Company",
					"supplier_group": ensure_leaf_supplier_group(),
				}
			).insert(ignore_permissions=True)
		cls.supplier = supplier_name

	def test_a_return_of_10_leaves_remaining_qty_at_10_and_refuses_11(self):
		po, asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)

		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].received_qty, 100)
		self.assertEqual(self._offered_qty(po), 10)
		self.assertEqual(self._portal_remaining(po), 10)
		self.assertEqual(self._portal_search_qty(po), 10)

		refused = make_test_asn(purchase_order=po, qty=11)
		with self.assertRaises(frappe.ValidationError) as raised:
			refused.insert(ignore_permissions=True)

		message = str(raised.exception)
		self.assertIn("Shipped qty 11.0 exceeds remaining PO qty 10.0", message)

		allowed = make_test_asn(purchase_order=po, qty=10)
		allowed.insert(ignore_permissions=True)

	def test_a_ten_percent_item_allowance_leaves_remaining_qty_at_20_and_refuses_21(self):
		"""Item allowance wins over Stock Settings. 21 is refused; the message hides stock figures."""
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=10, stock_allowance=50):
			self.assertEqual(self._offered_qty(po), 20)
			self.assertEqual(self._portal_remaining(po), 20)
			self.assertEqual(self._portal_search_qty(po), 20)

			refused = make_test_asn(purchase_order=po, qty=21)
			with self.assertRaises(frappe.ValidationError) as raised:
				refused.insert(ignore_permissions=True)

			message = str(raised.exception)
			self.assertIn("Shipped qty 21.0 exceeds remaining PO qty 20.0", message)
			for hidden in ("On Hand", "In Transit", "Maximum Stock"):
				self.assertNotIn(hidden, message)

			make_test_asn(purchase_order=po, qty=20).insert(ignore_permissions=True)

	def test_submit_refuses_shipped_qty_past_the_allowance(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=10, stock_allowance=0):
			draft = make_test_asn(purchase_order=po, qty=20)
			draft.insert(ignore_permissions=True)
			draft.items[0].qty = 21
			with self.assertRaises(frappe.ValidationError) as raised:
				draft.submit()
			self.assertIn("Shipped qty 21.0 exceeds remaining PO qty 20.0", str(raised.exception))

	def test_stock_settings_allowance_is_used_when_the_item_has_none(self):
		"""The Item column cannot store an unset allowance. Zero is what ERPNext reads as none."""
		item_code = _ensure_item("_Test ASN Unset Allowance Item")
		po, _asn, _purchase_return = self._accept_and_return(
			ordered=100, accepted=100, returned=10, item_code=item_code
		)
		self._assert_stock_settings_allowance_of_10_leaves_20(po)

	def test_a_zero_item_allowance_falls_through_to_stock_settings(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		self._assert_stock_settings_allowance_of_10_leaves_20(po)

	def test_a_zero_percent_allowance_stops_at_ordered_minus_received_minus_declared(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=0, stock_allowance=0):
			make_test_asn(purchase_order=po, qty=4).insert(ignore_permissions=True)
			self.assertEqual(self._offered_qty(po), 6)
			self.assertEqual(self._portal_remaining(po), 6)
			with self.assertRaises(frappe.ValidationError) as raised:
				make_test_asn(purchase_order=po, qty=7).insert(ignore_permissions=True)
			self.assertIn("Shipped qty 7.0 exceeds remaining PO qty 6.0", str(raised.exception))

	def test_a_desk_user_with_the_over_receive_role_is_refused_past_the_allowance(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		with _over_receipt_allowance(
			item_code=po.items[0].item_code,
			item_allowance=10,
			stock_allowance=0,
			role="System Manager",
		):
			self.assertIn("System Manager", frappe.get_roles())
			with self.assertRaises(frappe.ValidationError) as raised:
				make_test_asn(purchase_order=po, qty=21).insert(ignore_permissions=True)
			self.assertIn("Shipped qty 21.0 exceeds remaining PO qty 20.0", str(raised.exception))
			make_test_asn(purchase_order=po, qty=20).insert(ignore_permissions=True)

	def test_a_bulk_upload_starts_from_the_allowance_remaining_qty(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		dates = get_fiscal_year_test_dates()
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=10, stock_allowance=0):
			rows = [
				self._bulk_row(po, row_number=2, invoice_no="ALLOW-1", qty=20, dates=dates),
				self._bulk_row(po, row_number=3, invoice_no="ALLOW-2", qty=1, dates=dates),
			]
			with (
				patch(
					"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
					return_value=([], {}),
				),
				self.assertRaises(PortalValidationError) as raised,
			):
				create_bulk_asns_for_supplier(
					supplier=po.supplier, rows=rows, insert_asn=lambda **kwargs: None
				)

		messages = [error.get("message", "") for error in raised.exception.errors]
		self.assertIn("Row 3: qty 1 exceeds remaining PO qty 0.0.", messages)
		self.assertFalse(any(message.startswith("Row 2:") for message in messages))

	def test_shipped_qty_within_the_overflow_tolerance_is_allowed_and_past_it_is_refused(self):
		"""ERPNext allows overflow percent minus the allowance up to 0.01.

		20.005 is inside that tolerance. A further 0.01 crosses it. The displayed Remaining Qty stays 20.
		"""
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=10, stock_allowance=0):
			self.assertEqual(self._offered_qty(po), 20)
			make_test_asn(purchase_order=po, qty=20.005).insert(ignore_permissions=True)
			with self.assertRaises(frappe.ValidationError) as raised:
				make_test_asn(purchase_order=po, qty=0.01).insert(ignore_permissions=True)
			self.assertIn("exceeds remaining PO qty", str(raised.exception))

	def test_picker_and_portal_hide_the_line_when_remaining_qty_is_zero(self):
		po = self._submitted_purchase_order(qty=100)
		asn = make_test_asn(purchase_order=po, qty=100)
		asn.insert(ignore_permissions=True)
		asn.submit()
		self._purchase_receipt(po, asn, qty=100)

		self.assertEqual(get_purchase_order_items(po.name), [])
		self.assertEqual(self._portal_remaining(po), 0)

		open_po = self._submitted_purchase_order(qty=10)
		make_test_asn(purchase_order=open_po, qty=10).insert(ignore_permissions=True)
		self.assertEqual(get_purchase_order_items(open_po.name), [])
		self.assertEqual(self._portal_remaining(open_po), 0)
		self.assertEqual(self._portal_search_qty(open_po), 0)

	def test_amended_receipt_records_received_qty_on_the_asn(self):
		po = self._submitted_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		asn.submit()
		receipt = self._purchase_receipt(po, asn, qty=10)
		receipt.cancel()
		asn.reload()
		self.assertEqual(flt(asn.items[0].received_qty), 0)

		# Desk Amend copies no_copy fields too, so the old map arrives keyed by the old row names.
		amended = frappe.copy_doc(receipt)
		amended.docstatus = 0
		amended.amended_from = receipt.name
		amended.insert(ignore_permissions=True)
		self._submit_purchase_receipt(amended)

		asn.reload()
		self.assertEqual(flt(asn.items[0].received_qty), 10)
		self.assertEqual(asn.status, "Received")

		amended.cancel()
		asn.reload()
		self.assertEqual(flt(asn.items[0].received_qty), 0)

	def test_an_unmapped_row_skips_the_split_line_another_receipt_filled(self):
		po = self._submitted_purchase_order(qty=10)
		asn = make_test_asn_with_two_items(purchase_order=po, qty=5)
		asn.insert(ignore_permissions=True)
		asn.submit()
		self._purchase_receipt(po, asn, qty=5)

		second = self._purchase_receipt(po, asn, qty=5, submit=False)
		second.db_set("asn_items", None, notify=False)
		second.reload()
		self._submit_purchase_receipt(second)

		asn.reload()
		self.assertEqual([flt(row.received_qty) for row in asn.items], [5, 5])
		self.assertEqual(asn.status, "Received")

	def test_an_added_row_shares_its_receipts_line_before_one_another_receipt_filled(self):
		po = self._submitted_purchase_order(qty=10)
		asn = make_test_asn_with_two_items(purchase_order=po, qty=5)
		asn.insert(ignore_permissions=True)
		asn.submit()
		first = self._purchase_receipt(po, asn, qty=5, submit=False)
		first.db_set(
			"asn_items",
			json.dumps({first.items[0].name: {"asn_item_name": asn.items[1].name}}),
			notify=False,
		)
		first.reload()
		self._submit_purchase_receipt(first)

		second = self._purchase_receipt(po, asn, qty=3, submit=False)
		second.reload()
		split = second.items[0].as_dict(no_default_fields=True)
		split.update(qty=2, received_qty=2, stock_qty=2, received_stock_qty=2)
		second.append("items", split)
		second.save(ignore_permissions=True)
		self._submit_purchase_receipt(second)

		asn.reload()
		self.assertEqual([flt(row.received_qty) for row in asn.items], [5, 5])
		self.assertEqual(asn.status, "Received")

	def test_a_row_re_added_on_a_draft_receipt_records_received_qty_on_the_asn(self):
		po = self._submitted_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		asn.submit()
		receipt = self._purchase_receipt(po, asn, qty=10, submit=False)
		receipt.reload()

		row = receipt.items[0].as_dict(no_default_fields=True)
		receipt.set("items", [])
		receipt.append("items", row)
		receipt.save(ignore_permissions=True)
		self._submit_purchase_receipt(receipt)

		asn.reload()
		self.assertEqual(flt(asn.items[0].received_qty), 10)
		self.assertEqual(asn.status, "Received")

	def test_submit_refuses_again_after_the_return_is_cancelled(self):
		po, asn, purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		draft = make_test_asn(purchase_order=po, qty=10)
		draft.insert(ignore_permissions=True)

		purchase_return.cancel()
		po.reload()
		asn.reload()

		self.assertEqual(flt(po.items[0].received_qty), 100)
		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].received_qty, 100)
		with self.assertRaises(frappe.ValidationError) as saved:
			draft.save()
		self.assertIn("exceeds remaining PO qty", str(saved.exception))
		draft.reload()
		with self.assertRaises(frappe.ValidationError) as submitted:
			draft.submit()
		self.assertIn("exceeds remaining PO qty", str(submitted.exception))

	def test_a_draft_and_an_open_shipment_consume_remaining_qty_until_a_short_receipt_closes_it(self):
		po = self._submitted_purchase_order(qty=10)
		make_test_asn(purchase_order=po, qty=6).insert(ignore_permissions=True)
		self.assertEqual(self._offered_qty(po), 4)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=po, qty=5).insert(ignore_permissions=True)

		open_po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=open_po, qty=100)
		shipment.insert(ignore_permissions=True)
		shipment.submit()
		self.assertEqual(self._offered_qty(open_po), 0)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=open_po, qty=1).insert(ignore_permissions=True)

		# #134: the short receipt closes the shipment, so the 20 never delivered is freed.
		self._purchase_receipt(open_po, shipment, qty=80)
		self.assertEqual(frappe.db.get_value("ASN", shipment.name, "status"), "Closed")
		self.assertEqual(self._offered_qty(open_po), 20)

	def test_editing_a_draft_offers_the_same_remaining_qty_on_the_desk_and_the_portal(self):
		"""Ordered 10, this draft declares 6. Leaving the draft out, both doors offer 10."""
		po = self._submitted_purchase_order(qty=10)
		draft = make_test_asn(purchase_order=po, qty=6)
		draft.insert(ignore_permissions=True)

		offered = get_purchase_order_items(po.name, draft.name)
		_rows, remaining = fetch_purchase_order_items([po.name], exclude_asn_name=draft.name)

		self.assertEqual(offered[0]["qty"], 10)
		self.assertEqual(remaining[po.items[0].name], 10)
		self.assertEqual(self._portal_search_qty(po, asn_name=draft.name), 10)

	def test_the_portal_leaves_out_only_this_suppliers_draft(self):
		"""Ordered 10, this draft declares 6. Naming that draft, the portal still accepts 10.

		A submitted shipment, or a draft that belongs to someone else, stays in the count.
		"""
		from pathlib import Path

		from asn_module.templates.pages import asn_new

		po = self._submitted_purchase_order(qty=10)
		draft = make_test_asn(purchase_order=po, qty=6)
		draft.insert(ignore_permissions=True)

		frappe.db.set_value("ASN", draft.name, "supplier", f"Other-{po.supplier}")
		self.assertEqual(self._portal_search_qty(po, asn_name=draft.name), 4)
		self.assertEqual(self._portal_page_asn_name(po.supplier, draft.name), "")

		frappe.db.set_value("ASN", draft.name, "supplier", po.supplier)
		self.assertEqual(self._portal_search_qty(po, asn_name=draft.name), 10)
		self.assertEqual(self._portal_page_asn_name(po.supplier, draft.name), draft.name)
		created = self._portal_single_asn(po, qty=10, asn_name=draft.name)
		self.assertEqual(created.asn_names, [draft.name])
		self.assertEqual(flt(frappe.db.get_value("ASN Item", {"parent": draft.name}, "qty")), 10)

		other = self._submitted_purchase_order(qty=10)
		submitted = make_test_asn(purchase_order=other, qty=6)
		submitted.insert(ignore_permissions=True)
		submitted.submit()
		self.assertEqual(self._portal_search_qty(other, asn_name=submitted.name), 4)
		self.assertEqual(self._portal_page_asn_name(other.supplier, submitted.name), "")
		with self.assertRaises(PortalValidationError) as raised:
			self._portal_single_asn(other, qty=10, asn_name=submitted.name)
		self.assertIn("exceeds remaining PO qty 4", str(raised.exception))

		page = Path(asn_new.__file__).with_name("asn_new.html").read_text()
		self.assertIn('name="asn_name"', page)
		self.assertIn("asn_name=${encodeURIComponent", page)

	def _portal_page_asn_name(self, supplier: str, asn_name: str) -> str:
		from asn_module.templates.pages import asn_new

		context = frappe._dict()
		with (
			patch(
				"asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace(method="GET", files={})
			),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value=supplier),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier",
				return_value=[],
			),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"asn_name": asn_name}),
		):
			asn_new.get_context(context)
		return context.asn_name or ""

	def _portal_single_asn(self, po, *, qty: float, asn_name: str):
		from asn_module.templates.pages import asn_new
		from asn_module.templates.pages.asn_new_services import ParsedSingleRow

		po_item = po.items[0]
		dates = get_fiscal_year_test_dates()
		invoice_no = f"PORTAL-DRAFT-{frappe.generate_hash(length=6)}"
		form = {
			"asn_name": asn_name,
			"supplier_invoice_no": invoice_no,
			"supplier_invoice_date": dates["supplier_invoice_date"],
			"expected_delivery_date": dates["expected_delivery_date"],
			"supplier_invoice_amount": str(float(po_item.rate or 1) * qty),
			"vehicle_number": "MH12AB1234",
		}
		row = ParsedSingleRow(
			row_number=1,
			purchase_order=po.name,
			sr_no=str(po_item.idx),
			item_code=po_item.item_code,
			uom=po_item.uom,
			qty=qty,
			rate=float(po_item.rate or 1),
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", frappe._dict(form)),
			patch("asn_module.templates.pages.asn_new._request_list", return_value=[po.name]),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=[row]),
		):
			return asn_new._create_single_asn(po.supplier)

	def test_saving_an_existing_asn_does_not_count_its_own_shipped_qty_twice(self):
		po = self._submitted_purchase_order(qty=10)
		draft = make_test_asn(purchase_order=po, qty=6)
		draft.insert(ignore_permissions=True)

		draft.items[0].qty = 10
		draft.save()

		self.assertEqual(flt(draft.items[0].qty), 10)
		self.assertEqual(self._offered_qty(po), 0)

	def test_saving_a_partly_received_asn_does_not_count_its_receipt_twice(self):
		po = self._submitted_purchase_order(qty=100)
		draft = make_test_asn(purchase_order=po, qty=100)
		draft.insert(ignore_permissions=True)
		frappe.db.set_value("Purchase Order Item", po.items[0].name, "received_qty", 80)
		draft.items[0].received_qty = 80

		draft.save()
		self.assertEqual(flt(draft.items[0].qty), 100)

		draft.items[0].qty = 101
		with self.assertRaises(frappe.ValidationError) as raised:
			draft.save()
		self.assertIn("Shipped qty 101", str(raised.exception))
		self.assertIn("remaining PO qty 100", str(raised.exception))

	def test_two_asn_lines_for_one_purchase_order_item_are_summed(self):
		po = self._submitted_purchase_order(qty=10)
		over = make_test_asn_with_two_items(purchase_order=po, qty=6)
		with self.assertRaises(frappe.ValidationError) as raised:
			over.insert(ignore_permissions=True)
		self.assertIn("Shipped qty 12.0 exceeds remaining PO qty 10.0", str(raised.exception))

		fitting = make_test_asn_with_two_items(purchase_order=po, qty=4)
		fitting.items[1].qty = 6
		fitting.insert(ignore_permissions=True)
		self.assertEqual(self._offered_qty(po), 0)

	def test_a_closed_shortfall_can_be_declared_again_and_an_unreceipted_close_frees_the_order(self):
		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=100)
		shipment.insert(ignore_permissions=True)
		shipment.submit()
		self._purchase_receipt(po, shipment, qty=80)
		frappe.db.set_value("ASN", shipment.name, "status", "Closed", update_modified=False)

		self.assertEqual(self._offered_qty(po), 20)
		make_test_asn(purchase_order=po, qty=20).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=po, qty=1).insert(ignore_permissions=True)

		open_po = self._submitted_purchase_order(qty=100)
		closed = make_test_asn(purchase_order=open_po, qty=100)
		closed.insert(ignore_permissions=True)
		closed.submit()
		frappe.db.set_value("ASN", closed.name, "status", "Closed", update_modified=False)

		self.assertEqual(self._offered_qty(open_po), 100)
		make_test_asn(purchase_order=open_po, qty=100).insert(ignore_permissions=True)

	def test_an_unlinked_receipt_and_return_leave_remaining_qty_at_10(self):
		po = self._submitted_purchase_order(qty=100)
		receipt = self._purchase_receipt(po, None, qty=100)
		self._purchase_return(receipt, qty=10)

		self.assertEqual(self._offered_qty(po), 10)
		self.assertEqual(self._portal_remaining(po), 10)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=po, qty=11).insert(ignore_permissions=True)
		make_test_asn(purchase_order=po, qty=10).insert(ignore_permissions=True)

	def test_rejected_quantity_consumes_remaining_qty_until_it_is_returned(self):
		po = self._submitted_purchase_order(qty=100)
		receipt = self._purchase_receipt(po, None, qty=90, rejected_qty=10)
		po.reload()
		self.assertEqual(flt(po.items[0].received_qty), 100)
		self.assertEqual(self._offered_qty(po), 0)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=po, qty=10).insert(ignore_permissions=True)

		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
			make_purchase_return_against_rejected_warehouse,
		)

		rejected_return = make_purchase_return_against_rejected_warehouse(receipt.name)
		self._submit_purchase_receipt(rejected_return)
		po.reload()
		self.assertEqual(flt(po.items[0].received_qty), 90)
		self.assertEqual(self._offered_qty(po), 10)

	def test_a_stock_updating_purchase_invoice_consumes_remaining_qty(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		po = self._submitted_purchase_order(qty=100)
		invoice = make_purchase_invoice(po.name)
		invoice.update_stock = 1
		fill_custom_fiscal_year(invoice)
		invoice.insert(ignore_permissions=True)
		invoice.submit()
		po.reload()

		self.assertEqual(flt(po.items[0].received_qty), 100)
		self.assertEqual(self._offered_qty(po), 0)
		with self.assertRaises(frappe.ValidationError):
			make_test_asn(purchase_order=po, qty=1).insert(ignore_permissions=True)

	def test_a_direct_receipt_on_a_line_with_no_asn_submits(self):
		po = self._submitted_purchase_order(qty=10)
		other_po = self._submitted_purchase_order(qty=10)
		other_shipment = make_test_asn(purchase_order=other_po, qty=10)
		other_shipment.insert(ignore_permissions=True)
		other_shipment.submit()

		receipt = self._purchase_receipt(po, None, qty=10)

		self.assertEqual(receipt.docstatus, 1)
		other_shipment.reload()
		self.assertEqual(flt(other_shipment.items[0].received_qty), 0)
		self.assertEqual(other_shipment.status, "Submitted")

	def test_a_direct_receipt_within_remaining_qty_leaves_the_open_asn_alone(self):
		"""PO 100 with ASN-1 open for 10: a direct receipt for exactly 90 is the boundary."""
		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=10)
		shipment.insert(ignore_permissions=True)
		shipment.submit()

		receipt = self._purchase_receipt(po, None, qty=90)

		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)
		self.assertEqual(shipment.status, "Submitted")
		self.assertEqual(self._offered_qty(po), 0)

		receipt.cancel()
		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)
		self.assertEqual(shipment.status, "Submitted")
		self.assertEqual(self._offered_qty(po), 90)

	def test_a_direct_receipt_above_remaining_qty_names_the_asn_to_scan(self):
		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=10)
		shipment.insert(ignore_permissions=True)
		shipment.submit()

		receipt = self._purchase_receipt(po, None, qty=95, submit=False)
		with self.assertRaises(frappe.ValidationError) as raised:
			self._submit_purchase_receipt(receipt)

		self.assertIn(
			f"Row 1: 5.0 of {po.items[0].item_code} on {po.name} row 1 is already declared on "
			f"{shipment.name}; receive it by scanning {shipment.name}",
			str(raised.exception),
		)
		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)

	def test_a_direct_receipt_may_use_the_over_receipt_allowance_no_asn_covers(self):
		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=10)
		shipment.insert(ignore_permissions=True)
		shipment.submit()

		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=10, stock_allowance=0):
			refused = self._purchase_receipt(po, None, qty=101, submit=False)
			with self.assertRaises(frappe.ValidationError) as raised:
				self._submit_purchase_receipt(refused)
			self.assertIn(f"Row 1: 1.0 of {po.items[0].item_code}", str(raised.exception))

			self._purchase_receipt(po, None, qty=100)

		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)

	def test_a_stock_invoice_follows_the_direct_receipt_rule(self):
		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=10)
		shipment.insert(ignore_permissions=True)
		shipment.submit()

		refused = self._stock_invoice(po, qty=95)
		with self.assertRaises(frappe.ValidationError) as raised:
			refused.submit()
		self.assertIn(
			f"Row 1: 5.0 of {po.items[0].item_code} on {po.name} row 1 is already declared on "
			f"{shipment.name}",
			str(raised.exception),
		)

		invoice = self._stock_invoice(po, qty=90)
		invoice.submit()
		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)
		self.assertEqual(shipment.status, "Submitted")

		invoice.cancel()
		shipment.reload()
		self.assertEqual(flt(shipment.items[0].received_qty), 0)
		self.assertEqual(shipment.status, "Submitted")

	def test_an_invoice_billed_against_a_receipt_is_not_checked(self):
		from asn_module.handlers.purchase_invoice import on_purchase_invoice_before_submit

		po = self._submitted_purchase_order(qty=100)
		shipment = make_test_asn(purchase_order=po, qty=100)
		shipment.insert(ignore_permissions=True)
		shipment.submit()
		row = frappe._dict(
			idx=1,
			po_detail=po.items[0].name,
			purchase_receipt="PR-BILLED",
			qty=100,
			stock_qty=100,
			conversion_factor=1,
		)

		on_purchase_invoice_before_submit(frappe._dict(update_stock=1, is_return=0, items=[row]))

		row.purchase_receipt = None
		with self.assertRaises(frappe.ValidationError):
			on_purchase_invoice_before_submit(frappe._dict(update_stock=1, is_return=0, items=[row]))

	def test_a_closed_or_on_hold_purchase_order_accepts_no_shipped_qty(self):
		for status in ("Closed", "On Hold"):
			po = self._submitted_purchase_order(qty=10)
			frappe.db.set_value("Purchase Order", po.name, "status", status, update_modified=False)

			self.assertEqual(self._offered_qty(po), 0)
			self.assertEqual(self._portal_remaining(po), 0)
			with self.assertRaises(frappe.ValidationError) as raised:
				make_test_asn(purchase_order=po, qty=1).insert(ignore_permissions=True)
			self.assertIn("exceeds remaining PO qty 0", str(raised.exception))

	def test_a_conversion_factor_other_than_one_still_uses_purchase_uom(self):
		po = self._purchase_order_in_boxes(qty=10, conversion_factor=12)
		self._purchase_receipt(po, None, qty=4)
		po.reload()

		self.assertEqual(flt(po.items[0].received_qty), 4)
		self.assertEqual(flt(po.items[0].conversion_factor), 12)
		self.assertEqual(self._offered_qty(po), 6)
		with self.assertRaises(frappe.ValidationError) as raised:
			make_test_asn(purchase_order=po, qty=7).insert(ignore_permissions=True)
		self.assertIn("exceeds remaining PO qty 6", str(raised.exception))
		make_test_asn(purchase_order=po, qty=6).insert(ignore_permissions=True)

	def test_a_later_bulk_row_sees_what_an_earlier_row_took_after_a_return(self):
		po, _asn, _purchase_return = self._accept_and_return(ordered=100, accepted=100, returned=10)
		dates = get_fiscal_year_test_dates()
		rows = [
			self._bulk_row(po, row_number=1, invoice_no="REM-RET-1", qty=6, dates=dates),
			self._bulk_row(po, row_number=2, invoice_no="REM-RET-2", qty=5, dates=dates),
			self._bulk_row(po, row_number=3, invoice_no="REM-RET-3", qty=4, dates=dates),
		]
		with (
			patch(
				"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
				return_value=([], {}),
			),
			self.assertRaises(PortalValidationError) as raised,
		):
			create_bulk_asns_for_supplier(supplier=po.supplier, rows=rows, insert_asn=lambda **kwargs: None)

		messages = [error.get("message", "") for error in raised.exception.errors]
		self.assertIn("Row 2: qty 5 exceeds remaining PO qty 4.0.", messages)
		self.assertFalse(any(message.startswith("Row 3:") for message in messages))

	def _submitted_purchase_order(self, *, qty: float, item_code: str | None = None):
		return build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Remaining Qty Return Tax",
			supplier=self.supplier,
			qty=qty,
			item_code=item_code or _ensure_item(),
		)

	def _accept_and_return(
		self, *, ordered: float, accepted: float, returned: float, item_code: str | None = None
	):
		po = self._submitted_purchase_order(qty=ordered, item_code=item_code)
		asn = make_test_asn(purchase_order=po, qty=accepted)
		asn.insert(ignore_permissions=True)
		asn.submit()

		receipt = self._purchase_receipt(po, asn, qty=accepted)
		purchase_return = self._purchase_return(receipt, qty=returned)
		asn.reload()
		po.reload()
		self.assertEqual(flt(po.items[0].received_qty), ordered - returned)
		return po, asn, purchase_return

	def _purchase_receipt(self, po, asn, *, qty, rejected_qty=0, submit=True):
		row = {
			"item_code": po.items[0].item_code,
			"qty": qty,
			"rate": po.items[0].rate,
			"uom": po.items[0].uom,
			"conversion_factor": po.items[0].conversion_factor or 1,
			"purchase_order": po.name,
			"purchase_order_item": po.items[0].name,
			"warehouse": po.items[0].warehouse,
		}
		if rejected_qty:
			row["rejected_qty"] = rejected_qty
			row["rejected_warehouse"] = self._rejected_warehouse(po)
		payload = {
			"doctype": "Purchase Receipt",
			"supplier": po.supplier,
			"company": po.company,
			"items": [row],
		}
		if asn:
			payload["asn"] = asn.name
		receipt = frappe.get_doc(payload)
		apply_receipt_site_requirements(receipt)
		receipt.insert(ignore_permissions=True)
		if asn:
			# Row names exist only after insert, so the map is keyed by the row's name.
			receipt.db_set(
				"asn_items",
				json.dumps({receipt.items[0].name: {"asn_item_name": asn.items[0].name}}),
				notify=False,
			)
		if submit:
			self._submit_purchase_receipt(receipt)
		return receipt

	def _stock_invoice(self, po, *, qty):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		invoice = make_purchase_invoice(po.name)
		invoice.update_stock = 1
		fill_custom_fiscal_year(invoice)
		invoice.items[0].qty = qty
		invoice.insert(ignore_permissions=True)
		return invoice

	def _purchase_return(self, receipt, *, qty):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_return

		purchase_return = make_purchase_return(receipt.name)
		purchase_return.items[0].qty = -qty
		purchase_return.items[0].received_qty = -qty
		self._submit_purchase_receipt(purchase_return)
		return purchase_return

	def _submit_purchase_receipt(self, receipt):
		with (
			patch("asn_module.handlers.purchase_receipt.store_scan_code"),
		):
			receipt.submit()

	def _rejected_warehouse(self, po) -> str:
		name = frappe.db.get_value(
			"Warehouse",
			{"company": po.company, "is_group": 0, "name": ["!=", po.items[0].warehouse]},
			"name",
		)
		if name:
			return name
		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": "_Test ASN Rejected Warehouse",
				"company": po.company,
			}
		)
		warehouse.insert(ignore_permissions=True)
		return warehouse.name

	def _purchase_order_in_boxes(self, *, qty: float, conversion_factor: float):
		item_code = _ensure_item("_Test ASN Purchase UOM Item")
		if not frappe.db.exists("UOM", "Box"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Box"}).insert(ignore_permissions=True)
		item = frappe.get_doc("Item", item_code)
		if not any(row.uom == "Box" for row in item.get("uoms") or []):
			item.append("uoms", {"uom": "Box", "conversion_factor": conversion_factor})
			item.save(ignore_permissions=True)

		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test ASN Remaining Qty UOM Tax",
			supplier=self.supplier,
			item_code=item_code,
			qty=qty,
			do_not_submit=True,
		)
		po.items[0].uom = "Box"
		po.items[0].conversion_factor = conversion_factor
		po.items[0].stock_qty = qty * conversion_factor
		po.save(ignore_permissions=True)
		po.submit()
		return po

	def _bulk_row(self, po, *, row_number: int, invoice_no: str, qty: float, dates: dict):
		po_item = po.items[0]
		return ParsedBulkRow(
			row_number=row_number,
			supplier_invoice_no=invoice_no,
			supplier_invoice_date=dates["supplier_invoice_date"],
			expected_delivery_date=dates["expected_delivery_date"],
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

	def _assert_stock_settings_allowance_of_10_leaves_20(self, po):
		"""A zero Item allowance uses a 10% Stock Settings allowance: 20 is allowed, 21 is refused."""
		with _over_receipt_allowance(item_code=po.items[0].item_code, item_allowance=0, stock_allowance=10):
			self.assertEqual(self._offered_qty(po), 20)
			with self.assertRaises(frappe.ValidationError) as raised:
				make_test_asn(purchase_order=po, qty=21).insert(ignore_permissions=True)
			self.assertIn("exceeds remaining PO qty 20.0", str(raised.exception))
			make_test_asn(purchase_order=po, qty=20).insert(ignore_permissions=True)

	def _offered_qty(self, po) -> float:
		offered = get_purchase_order_items(po.name)
		if not offered:
			return 0
		return offered[0]["qty"]

	def _portal_remaining(self, po) -> float:
		_rows, remaining = fetch_purchase_order_items([po.name])
		return remaining[po.items[0].name]

	def _portal_search_qty(self, po, asn_name: str | None = None) -> float:
		from asn_module.templates.pages import asn_new_search

		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user",
				return_value=po.supplier,
			),
		):
			rows = asn_new_search.search_purchase_order_items(purchase_order=po.name, asn_name=asn_name)
		if not rows:
			return 0
		return rows[0]["remaining_qty"]


_original_create_purchase_order = create_purchase_order


def _create_purchase_order_with_mandatory_fields(**kwargs):
	"""Wrap create_purchase_order() to satisfy this bench's mandatory custom_order_type/taxes fields.

	See asn_module.utils.test_setup.build_purchase_order_with_mandatory_fields for why this
	bench-specific mandatory-field workaround is needed.

	Uses the module-level reference captured before create_purchase_order() gets patched
	(see TestASNStockCap.setUp), since this function replaces that name for the duration
	of each test and must not call back into itself.
	"""
	do_not_submit = kwargs.pop("do_not_submit", False)
	return build_purchase_order_with_mandatory_fields(
		_original_create_purchase_order,
		tax_description="_Test ASN Stock Cap Controller Tax",
		do_not_submit=do_not_submit,
		**kwargs,
	)


class TestASNStockCap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

	def setUp(self):
		# make_test_asn() resolves create_purchase_order() as a module-global at call
		# time, so patching the name here is enough to route its PO fixture creation
		# through the mandatory-field workaround without touching the brief's verbatim
		# test bodies below.
		patcher = patch(
			"asn_module.asn_module.doctype.asn.test_asn.create_purchase_order",
			side_effect=_create_purchase_order_with_mandatory_fields,
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _breach(self):
		return make_test_breach(on_hand=90.0)

	def test_submit_is_blocked_when_cap_is_breached(self):
		asn = make_test_asn(qty=5)
		with patch("asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc", return_value=[]):
			asn.insert()

		frappe.local.message_log = []
		with patch(
			"asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc",
			return_value=[self._breach()],
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				asn.submit()

		self.assertIn("WIDGET", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "docstatus"), 0)
		self.assertNotIn("Stock Cap Warning", message_log_text())

	def test_save_warns_but_succeeds_when_cap_is_breached(self):
		asn = make_test_asn(qty=5)
		frappe.local.message_log = []
		with patch(
			"asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc",
			return_value=[self._breach()],
		):
			asn.insert()

		self.assertTrue(frappe.db.exists("ASN", asn.name))
		self.assertIn("WIDGET", message_log_text())

	def test_submit_succeeds_when_no_breach(self):
		asn = make_test_asn(qty=5)
		with patch("asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc", return_value=[]):
			asn.insert()
			asn.submit()

		self.assertEqual(frappe.db.get_value("ASN", asn.name, "docstatus"), 1)
