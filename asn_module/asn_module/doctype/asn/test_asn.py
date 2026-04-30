from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate, today

from asn_module.asn_module.doctype.asn.asn import (
	get_item_transition_summary,
	get_po_items,
	get_purchase_order_items,
)
from asn_module.utils.test_setup import TEST_COMPANY_NAME, before_tests

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

	supplier_group = _first_or_none("Supplier Group") or "All Supplier Groups"
	supplier_data = {
		"doctype": "Supplier",
		"supplier_name": supplier_name,
		"supplier_type": "Company",
	}
	if supplier_group:
		supplier_data["supplier_group"] = supplier_group

	supplier = frappe.get_doc(supplier_data)
	supplier.insert(ignore_permissions=True)
	return supplier.name


def _ensure_item(item_code: str = "_Test ASN Item"):
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
		return item_code

	item_group = _first_or_none("Item Group") or "All Item Groups"
	uom = _first_or_none("UOM") or "Nos"
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": uom,
			"inspection_required_before_purchase": 0,
		}
	)
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
	po = purchase_order or create_purchase_order(do_not_submit=True)
	po_item = po.items[0]

	return frappe.get_doc(
		{
			"doctype": "ASN",
			"supplier": supplier or po.supplier,
			"supplier_invoice_no": supplier_invoice_no or f"INV-{frappe.generate_hash(length=8)}",
			"supplier_invoice_date": today(),
			"expected_delivery_date": today(),
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
def _mock_asn_attachments():
	def fake_save_file(filename, *_args, **_kwargs):
		return SimpleNamespace(file_url=f"/files/{filename}")

	with (
		patch(
			"asn_module.asn_module.doctype.asn.asn.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}
		),
		patch(
			"asn_module.asn_module.doctype.asn.asn.generate_barcode",
			return_value={"image_base64": "ZmFrZS1iYXI="},
		),
		patch("asn_module.asn_module.doctype.asn.asn.save_file", side_effect=fake_save_file),
	):
		yield


@contextmanager
def real_asn_attachment_context():
	"""Use real ``generate_qr`` / ``generate_barcode`` / ``save_file`` on ASN submit (no mocks)."""
	yield


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

	def test_insert_rejects_empty_items(self):
		asn = make_test_asn()
		asn.set("items", [])

		with self.assertRaises(frappe.ValidationError):
			asn.insert(ignore_permissions=True)

	def test_insert_rejects_non_positive_qty(self):
		asn = make_test_asn(qty=0)

		with self.assertRaises(frappe.ValidationError):
			asn.insert(ignore_permissions=True)

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

		with _mock_asn_attachments():
			doc.submit()

		doc.cancel()

		duplicate = make_test_asn(supplier_invoice_no=invoice_no)
		duplicate.insert(ignore_permissions=True)

	def test_insert_rejects_shipped_qty_above_remaining_po_qty(self):
		po = create_purchase_order(qty=10, do_not_submit=True)
		existing = make_test_asn(purchase_order=po, qty=7)
		existing.insert(ignore_permissions=True)

		over_limit = make_test_asn(purchase_order=po, qty=4)

		with self.assertRaises(frappe.ValidationError):
			over_limit.insert(ignore_permissions=True)

	def test_insert_allows_duplicate_po_item_rows_within_remaining_po_qty(self):
		po = create_purchase_order(qty=10, do_not_submit=True)
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
		po = create_purchase_order(qty=10, do_not_submit=True)
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

	def test_validate_sets_supplier_invoice_amount_from_line_totals_when_zero(self):
		po = create_purchase_order(qty=2, do_not_submit=True, rate=100)
		asn = make_test_asn(purchase_order=po, qty=2)
		self.assertEqual(frappe.utils.flt(asn.supplier_invoice_amount), 0)
		asn.validate()
		self.assertEqual(frappe.utils.flt(asn.supplier_invoice_amount), 200)

	def test_validate_preserves_nonzero_supplier_invoice_amount(self):
		po = create_purchase_order(qty=2, do_not_submit=True, rate=100)
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

	def test_validate_po_qty_ignores_missing_purchase_order_item_qty(self):
		asn = make_test_asn()
		with (
			patch("asn_module.asn_module.doctype.asn.asn.frappe.get_all", return_value=[]),
			patch("asn_module.asn_module.doctype.asn.asn._get_shipped_qty_by_po_item", return_value={}),
		):
			asn._validate_po_qty()

	def test_submit_sets_status_date_and_attachments(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with _mock_asn_attachments():
			asn.submit()

		asn.reload()

		self.assertEqual(asn.status, "Submitted")
		self.assertEqual(str(asn.asn_date), today())
		self.assertEqual(asn.qr_code, f"/files/{asn.name}-qr.png")
		self.assertEqual(asn.barcode, f"/files/{asn.name}-barcode.png")

	def test_submit_with_real_qr_and_barcode_attachments(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with real_asn_attachment_context():
			asn.submit()

		asn.reload()
		self.assertEqual(asn.status, "Submitted")
		self.assertEqual(str(asn.asn_date), today())
		self.assertTrue(asn.qr_code)
		self.assertTrue(asn.barcode)
		self.assertIn("/files/", asn.qr_code)
		self.assertIn("/files/", asn.barcode)

	def test_cancel_sets_status_cancelled(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with _mock_asn_attachments():
			asn.submit()

		asn.cancel()
		asn.reload()

		self.assertEqual(asn.status, "Cancelled")

	def test_cancel_removes_scan_code_registry_rows(self):
		if not frappe.db.exists("DocType", "Scan Code"):
			return

		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with real_asn_attachment_context():
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

		with _mock_asn_attachments():
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

		self.assertEqual(mock_delete.call_count, 2)
		mock_delete.assert_any_call("Scan Code", {"source_doctype": "ASN", "source_name": asn.name})
		mock_delete.assert_any_call("ASN Transition Log", {"asn": asn.name})

	def test_before_cancel_deletes_linked_draft_purchase_receipts(self):
		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with _mock_asn_attachments():
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

	def test_update_receipt_status_sets_partially_received_and_updates_discrepancy_qty(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		asn.items[0].received_qty = 2
		asn.items[1].received_qty = 5

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.status, "Partially Received")
		self.assertEqual(asn.items[0].received_qty, 2)
		self.assertEqual(asn.items[1].received_qty, 5)
		self.assertEqual(asn.items[0].discrepancy_qty, 3)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_update_receipt_status_sets_received_when_all_items_fully_received(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		asn.items[0].received_qty = 5
		asn.items[1].received_qty = 5

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].discrepancy_qty, 0)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_update_receipt_status_works_for_submitted_asn(self):
		asn = make_test_asn_with_two_items(qty=5)
		asn.insert(ignore_permissions=True)

		with _mock_asn_attachments():
			asn.submit()

		asn.reload()
		asn.items[0].received_qty = 2
		asn.items[1].received_qty = 5

		asn.update_receipt_status()
		asn.reload()

		self.assertEqual(asn.docstatus, 1)
		self.assertEqual(asn.status, "Partially Received")
		self.assertEqual(asn.items[0].received_qty, 2)
		self.assertEqual(asn.items[1].received_qty, 5)
		self.assertEqual(asn.items[0].discrepancy_qty, 3)
		self.assertEqual(asn.items[1].discrepancy_qty, 0)

	def test_amendment_resets_copied_lifecycle_fields(self):
		frappe.reload_doc("asn_module", "doctype", "asn")

		asn = make_test_asn()
		asn.insert(ignore_permissions=True)

		with _mock_asn_attachments():
			asn.submit()

		asn.cancel()

		amended = frappe.copy_doc(asn, ignore_no_copy=False)
		amended.amended_from = asn.name
		amended.docstatus = 0

		self.assertIsNone(amended.status)
		self.assertIsNone(amended.asn_date)
		self.assertIsNone(amended.qr_code)
		self.assertIsNone(amended.barcode)

		amended.insert(ignore_permissions=True)

		self.assertEqual(amended.status, "Draft")
		self.assertEqual(amended.amended_from, asn.name)

	def test_get_purchase_order_items_returns_only_remaining_quantities(self):
		po = create_purchase_order(qty=10, do_not_submit=True)
		existing = make_test_asn(purchase_order=po, qty=6)
		existing.insert(ignore_permissions=True)

		items = get_purchase_order_items(po.name)

		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["purchase_order"], po.name)
		self.assertEqual(items[0]["purchase_order_item"], po.items[0].name)
		self.assertEqual(items[0]["qty"], 4)

	def test_get_po_items_filters_results_by_purchase_order_and_search_text(self):
		po = create_purchase_order(item_code=_ensure_item(), do_not_submit=True)

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
