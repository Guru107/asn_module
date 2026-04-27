from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError as FrappeValidationError
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages import asn_new
from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	ParsedSingleRow,
	PortalValidationError,
	resolve_po_item,
	validate_no_duplicate_po_sr_no,
	validate_supplier_invoices_not_reused,
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


def _fake_frappe_local():
	return SimpleNamespace(response={}, cache={})


class TestASNNewPortalPage(FrappeTestCase):
	def test_parse_single_rows_returns_empty_without_type_error_for_blank_form_lists(self):
		class _FakeForm:
			def getlist(self, fieldname):
				return []

		request = SimpleNamespace(form=_FakeForm())
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			rows = asn_new._parse_single_rows()
		self.assertEqual(rows, [])

	def test_parse_single_rows_parses_valid_row(self):
		class _FakeForm:
			def __init__(self):
				self.data = {
					"single_manual_purchase_order": ["PO-0001"],
					"single_manual_sr_no": ["1"],
					"single_manual_item_code": ["ITEM-001"],
					"single_manual_uom": ["Nos"],
					"single_manual_qty": ["10"],
					"single_manual_rate": ["25"],
				}

			def getlist(self, fieldname):
				return self.data.get(fieldname, [])

		request = SimpleNamespace(form=_FakeForm())
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			rows = asn_new._parse_single_rows()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].purchase_order, "PO-0001")
		self.assertEqual(rows[0].sr_no, "1")
		self.assertEqual(rows[0].item_code, "ITEM-001")
		self.assertEqual(rows[0].qty, 10)
		self.assertEqual(rows[0].rate, 25)

	def test_parse_single_rows_accepts_100_rows(self):
		class _FakeForm:
			def __init__(self):
				indexes = [str(i) for i in range(1, 101)]
				self.data = {
					"single_manual_purchase_order": ["PO-100"] * 100,
					"single_manual_sr_no": indexes,
					"single_manual_item_code": ["ITEM-001"] * 100,
					"single_manual_uom": ["Nos"] * 100,
					"single_manual_qty": ["1"] * 100,
					"single_manual_rate": ["10"] * 100,
				}

			def getlist(self, fieldname):
				return self.data.get(fieldname, [])

		request = SimpleNamespace(form=_FakeForm())
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			rows = asn_new._parse_single_rows()
		self.assertEqual(len(rows), 100)
		self.assertEqual(rows[0].sr_no, "1")
		self.assertEqual(rows[-1].sr_no, "100")

	def test_parse_bulk_csv_rows_accepts_strict_template(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,250,PO-0001,1,ITEM-001,10,25"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			rows = asn_new._parse_bulk_csv_rows()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].supplier_invoice_no, "INV-1")
		self.assertEqual(rows[0].purchase_order, "PO-0001")
		self.assertEqual(rows[0].sr_no, "1")
		self.assertEqual(rows[0].item_code, "ITEM-001")
		self.assertEqual(rows[0].rate, 25)
		self.assertEqual(rows[0].supplier_invoice_amount, 250)

	def test_parse_bulk_csv_rows_accepts_empty_rate(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,250,PO-0001,1,ITEM-001,10,"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			rows = asn_new._parse_bulk_csv_rows()
		self.assertEqual(len(rows), 1)
		self.assertIsNone(rows[0].rate)

	def test_parse_bulk_csv_rows_rejects_negative_rate_when_provided(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,250,PO-0001,1,ITEM-001,10,-1"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError),
		):
			asn_new._parse_bulk_csv_rows()

	def test_parse_bulk_csv_rows_rejects_empty_supplier_invoice_amount(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,,PO-0001,1,ITEM-001,10,25"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError),
		):
			asn_new._parse_bulk_csv_rows()

	def test_parse_bulk_csv_rows_rejects_header_order_mismatch(self):
		csv_content = (
			b"supplier_invoice_no,purchase_order,sr_no,item_code,qty,rate\nINV-1,PO-0001,1,ITEM-001,10,25\n"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError),
		):
			asn_new._parse_bulk_csv_rows()

	def test_parse_bulk_csv_rows_accepts_100_item_rows(self):
		rows = [
			f"INV-100,{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},,,,,,1000,PO-100,{idx},ITEM-001,1,10"
			for idx in range(1, 101)
		]
		csv_text = (
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate\n"
			+ "\n".join(rows)
			+ "\n"
		)
		request = SimpleNamespace(
			files={
				"bulk_items_csv": SimpleNamespace(
					filename="items_100.csv",
					stream=BytesIO(csv_text.encode("utf-8")),
				)
			}
		)
		with patch("asn_module.templates.pages.asn_new.frappe.request", request):
			parsed = asn_new._parse_bulk_csv_rows()
		self.assertEqual(len(parsed), 100)
		self.assertEqual(parsed[0].sr_no, "1")
		self.assertEqual(parsed[-1].sr_no, "100")

	def test_get_context_rejects_invalid_mode_inline(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "invalid"}),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
			patch("asn_module.templates.pages.asn_new.frappe.local", _fake_frappe_local()),
		):
			asn_new.get_context(context)
		self.assertEqual(context.active_tab, "single")
		self.assertTrue(context.single_errors)
		self.assertEqual(context.single_errors[0]["field"], "mode")

	def test_get_context_maps_frappe_validation_error_to_bulk_errors(self):
		context = SimpleNamespace()

		def _boom(*_a, **_k):
			raise FrappeValidationError("Quantity exceeds what is left on the purchase order.")

		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "bulk"}),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
			patch("asn_module.templates.pages.asn_new._create_bulk_asns", side_effect=_boom),
			patch("asn_module.templates.pages.asn_new.frappe.local", _fake_frappe_local()),
		):
			asn_new.get_context(context)
		self.assertEqual(context.active_tab, "bulk")
		self.assertTrue(context.bulk_errors)
		self.assertIn("Quantity exceeds", context.bulk_errors[0]["message"])
		self.assertEqual(context.bulk_errors[0]["field"], "asn")

	def test_get_context_maps_blank_frappe_validation_error_to_default_single_error(self):
		context = SimpleNamespace()

		def _boom(*_a, **_k):
			raise FrappeValidationError("")

		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "single"}),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
			patch("asn_module.templates.pages.asn_new._create_single_asn", side_effect=_boom),
			patch("asn_module.templates.pages.asn_new.frappe.local", _fake_frappe_local()),
		):
			asn_new.get_context(context)

		self.assertEqual(context.single_errors[0]["field"], "asn")
		self.assertIn("could not save", context.single_errors[0]["message"])

	def test_get_context_redirects_after_single_asn_create(self):
		context = SimpleNamespace()
		local = SimpleNamespace(flags=SimpleNamespace())
		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "single"}),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
			patch(
				"asn_module.templates.pages.asn_new._create_single_asn",
				return_value=asn_new.CreateResult(asn_names=["ASN-0001"]),
			),
			patch("asn_module.templates.pages.asn_new.frappe.db.get_value", return_value="asn/asn-0001"),
			patch("asn_module.templates.pages.asn_new.frappe.local", local),
			self.assertRaises(frappe.Redirect),
		):
			asn_new.get_context(context)

		self.assertEqual(local.flags.redirect_location, "/asn/asn-0001")

	def test_get_context_sets_bulk_success_after_bulk_create(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "bulk"}),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
			patch(
				"asn_module.templates.pages.asn_new._create_bulk_asns",
				return_value=asn_new.CreateResult(asn_names=["ASN-0001", "ASN-0002"]),
			),
			patch("asn_module.templates.pages.asn_new.frappe.local", _fake_frappe_local()),
		):
			asn_new.get_context(context)

		self.assertEqual(context.active_tab, "bulk")
		self.assertIn("ASN-0001", context.bulk_success)
		self.assertIn("ASN-0002", context.bulk_success)

	def test_validate_supplier_invoices_not_reused_raises_portal_error(self):
		with patch("asn_module.templates.pages.asn_new_services.frappe.db.exists", return_value="ASN-00001"):
			with self.assertRaises(PortalValidationError) as ctx:
				validate_supplier_invoices_not_reused("Supp-001", ["INV-DUP"])
		msgs = " ".join(e.get("message", "") for e in ctx.exception.errors)
		self.assertIn("INV-DUP", msgs)

	def test_service_rejects_duplicate_po_sr_no_in_same_invoice_group(self):
		rows = [
			ParsedBulkRow(
				row_number=2,
				supplier_invoice_no="INV-1",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0001",
				sr_no="10",
				item_code="ITEM-001",
				qty=1,
				rate=10,
			),
			ParsedBulkRow(
				row_number=3,
				supplier_invoice_no="INV-1",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0001",
				sr_no="10",
				item_code="ITEM-001",
				qty=1,
				rate=10,
			),
		]
		with self.assertRaises(PortalValidationError):
			validate_no_duplicate_po_sr_no(rows, invoice_no="INV-1")

	def test_service_resolve_po_item_rejects_zero_and_multiple_matches(self):
		with self.assertRaises(PortalValidationError):
			resolve_po_item(
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				row_number=1,
				invoice_no=None,
				rows_by_key={},
			)

		with self.assertRaises(PortalValidationError):
			resolve_po_item(
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				row_number=1,
				invoice_no=None,
				rows_by_key={
					("PO-0001", "1"): [
						SimpleNamespace(name="A", item_code="ITEM-001"),
						SimpleNamespace(name="B", item_code="ITEM-001"),
					]
				},
			)

	def test_create_single_asn_rejects_duplicate_po_sr_no(self):
		rows = [
			ParsedSingleRow(
				row_number=1,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				uom="Nos",
				qty=1,
				rate=10,
			),
			ParsedSingleRow(
				row_number=2,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				uom="Nos",
				qty=1,
				rate=10,
			),
		]
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001"]),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=rows),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
			patch(
				"asn_module.templates.pages.asn_new.fetch_purchase_order_items",
				return_value=(
					{("PO-0001", "1"): [SimpleNamespace(name="POI-1", item_code="ITEM-001", uom="Nos")]},
					{"POI-1": 10},
				),
			),
		):
			with self.assertRaises(PortalValidationError):
				asn_new._create_single_asn("Supp-001")

	def test_create_single_asn_requires_exactly_one_selected_po(self):
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001", "PO-0002"]),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
		):
			with self.assertRaises(PortalValidationError) as ctx:
				asn_new._create_single_asn("Supp-001")
		self.assertEqual(ctx.exception.errors[0]["field"], "selected_purchase_orders")

	def test_create_single_asn_rejects_empty_rows(self):
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001"]),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new.validate_supplier_invoices_not_reused"),
			patch("asn_module.templates.pages.asn_new._request_value", return_value="INV-1"),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=[]),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._create_single_asn("Supp-001")

		self.assertEqual(ctx.exception.errors[0]["field"], "rows")

	def test_create_single_asn_rejects_unselected_purchase_order_row(self):
		rows = [
			ParsedSingleRow(
				row_number=1,
				purchase_order="PO-0002",
				sr_no="1",
				item_code="ITEM-001",
				uom="Nos",
				qty=1,
				rate=10,
			)
		]
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001"]),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new.validate_supplier_invoices_not_reused"),
			patch("asn_module.templates.pages.asn_new._request_value", return_value="INV-1"),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=rows),
			patch(
				"asn_module.templates.pages.asn_new.fetch_purchase_order_items",
				return_value=({}, {}),
			),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._create_single_asn("Supp-001")

		self.assertEqual(ctx.exception.errors[0]["field"], "purchase_order")

	def test_create_single_asn_creates_payload_with_po_item_defaults(self):
		rows = [
			ParsedSingleRow(
				row_number=1,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				uom="",
				qty=2,
				rate=10,
			)
		]
		po_item = SimpleNamespace(name="POI-1", item_code="ITEM-001", uom="Nos")
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001"]),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new.validate_supplier_invoices_not_reused"),
			patch(
				"asn_module.templates.pages.asn_new._request_value",
				side_effect=lambda field: {
					"supplier_invoice_no": "INV-1",
					"supplier_invoice_date": _test_dates()["supplier_invoice_date"],
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
				}.get(field, ""),
			),
			patch("asn_module.templates.pages.asn_new._request_supplier_invoice_amount", return_value=20),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=rows),
			patch(
				"asn_module.templates.pages.asn_new.fetch_purchase_order_items",
				return_value=({("PO-0001", "1"): [po_item]}, {"POI-1": 5}),
			),
			patch(
				"asn_module.templates.pages.asn_new._insert_and_submit_asn",
				return_value=SimpleNamespace(name="ASN-0001"),
			) as insert_submit,
		):
			result = asn_new._create_single_asn("Supp-001")

		self.assertEqual(result.asn_names, ["ASN-0001"])
		kwargs = insert_submit.call_args.kwargs
		self.assertEqual(kwargs["supplier"], "Supp-001")
		self.assertEqual(kwargs["items"][0]["purchase_order_item"], "POI-1")
		self.assertEqual(kwargs["items"][0]["uom"], "Nos")

	def test_create_bulk_asn_rejects_multiple_purchase_orders_in_invoice_group(self):
		rows = [
			ParsedBulkRow(
				row_number=2,
				supplier_invoice_no="INV-MIX",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				qty=1,
				rate=10,
			),
			ParsedBulkRow(
				row_number=3,
				supplier_invoice_no="INV-MIX",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0002",
				sr_no="1",
				item_code="ITEM-002",
				qty=1,
				rate=10,
			),
		]
		with (
			patch("asn_module.templates.pages.asn_new._parse_bulk_csv_rows", return_value=rows),
			patch("asn_module.templates.pages.asn_new_services.enforce_bulk_limits"),
			patch("asn_module.templates.pages.asn_new_services.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new_services.validate_supplier_invoices_not_reused"),
			patch(
				"asn_module.templates.pages.asn_new_services.fetch_purchase_order_items",
				return_value=({}, {}),
			),
		):
			with self.assertRaises(PortalValidationError) as ctx:
				asn_new._create_bulk_asns("Supp-001")
		messages = " ".join(error.get("message", "") for error in ctx.exception.errors)
		self.assertIn("single Purchase Order", messages)

	def test_create_bulk_asn_creates_one_asn_per_invoice_group(self):
		rows = [
			ParsedBulkRow(
				row_number=2,
				supplier_invoice_no="INV-1",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				qty=1,
				rate=10,
			),
			ParsedBulkRow(
				row_number=3,
				supplier_invoice_no="INV-2",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=200,
				purchase_order="PO-0002",
				sr_no="1",
				item_code="ITEM-002",
				qty=1,
				rate=20,
			),
		]
		rows_by_key = {
			("PO-0001", "1"): [SimpleNamespace(name="POI-1", item_code="ITEM-001", uom="Nos", rate=10)],
			("PO-0002", "1"): [SimpleNamespace(name="POI-2", item_code="ITEM-002", uom="Nos", rate=20)],
		}
		remaining_qty = {"POI-1": 10, "POI-2": 10}
		mock_asn_1 = SimpleNamespace(name="ASN-0001")
		mock_asn_2 = SimpleNamespace(name="ASN-0002")

		with (
			patch("asn_module.templates.pages.asn_new._parse_bulk_csv_rows", return_value=rows),
			patch("asn_module.templates.pages.asn_new_services.enforce_bulk_limits"),
			patch("asn_module.templates.pages.asn_new_services.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new_services.validate_supplier_invoices_not_reused"),
			patch(
				"asn_module.templates.pages.asn_new_services.fetch_purchase_order_items",
				return_value=(rows_by_key, remaining_qty),
			),
			patch(
				"asn_module.templates.pages.asn_new._insert_and_submit_asn",
				side_effect=[mock_asn_1, mock_asn_2],
			) as mock_insert_submit,
		):
			result = asn_new._create_bulk_asns("Supp-001")

		self.assertEqual(result.asn_names, ["ASN-0001", "ASN-0002"])
		self.assertEqual(mock_insert_submit.call_count, 2)

	def test_create_bulk_asn_rejects_empty_csv(self):
		with (
			patch("asn_module.templates.pages.asn_new._parse_bulk_csv_rows", return_value=[]),
			patch("asn_module.templates.pages.asn_new_services.enforce_bulk_limits"),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._create_bulk_asns("Supp-001")

		self.assertEqual(ctx.exception.errors[0]["field"], "items_csv")

	def test_create_bulk_asn_aggregates_row_validation_failures(self):
		rows = [
			ParsedBulkRow(
				row_number=2,
				supplier_invoice_no="INV-1",
				supplier_invoice_date=_test_dates()["supplier_invoice_date"],
				expected_delivery_date=_test_dates()["expected_delivery_date"],
				lr_no="",
				lr_date="",
				transporter_name="",
				vehicle_number="",
				driver_contact="",
				supplier_invoice_amount=100,
				purchase_order="PO-0001",
				sr_no="99",
				item_code="ITEM-001",
				qty=1,
				rate=None,
			)
		]
		with (
			patch("asn_module.templates.pages.asn_new._parse_bulk_csv_rows", return_value=rows),
			patch("asn_module.templates.pages.asn_new_services.enforce_bulk_limits"),
			patch("asn_module.templates.pages.asn_new_services.validate_selected_purchase_orders"),
			patch("asn_module.templates.pages.asn_new_services.validate_supplier_invoices_not_reused"),
			patch(
				"asn_module.templates.pages.asn_new_services.fetch_purchase_order_items",
				return_value=({}, {}),
			),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._create_bulk_asns("Supp-001")

		fields = [error["field"] for error in ctx.exception.errors]
		self.assertIn("sr_no", fields)
		self.assertIn("bulk", fields)

	def test_create_single_asn_rejects_cumulative_qty_exceeding_remaining(self):
		rows = [
			ParsedSingleRow(
				row_number=1,
				purchase_order="PO-0001",
				sr_no="1",
				item_code="ITEM-001",
				uom="Nos",
				qty=6,
				rate=10,
			),
			ParsedSingleRow(
				row_number=2,
				purchase_order="PO-0001",
				sr_no="2",
				item_code="ITEM-002",
				uom="Nos",
				qty=5,
				rate=10,
			),
		]
		with (
			patch("asn_module.templates.pages.asn_new._request_list", return_value=["PO-0001"]),
			patch("asn_module.templates.pages.asn_new._parse_single_rows", return_value=rows),
			patch("asn_module.templates.pages.asn_new.validate_selected_purchase_orders"),
			patch(
				"asn_module.templates.pages.asn_new.fetch_purchase_order_items",
				return_value=(
					{
						("PO-0001", "1"): [SimpleNamespace(name="POI-1", item_code="ITEM-001", uom="Nos")],
						("PO-0001", "2"): [SimpleNamespace(name="POI-1", item_code="ITEM-002", uom="Nos")],
					},
					{"POI-1": 10},
				),
			),
		):
			with self.assertRaises(PortalValidationError):
				asn_new._create_single_asn("Supp-001")

	def test_get_context_returns_early_on_get(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="GET", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
		):
			asn_new.get_context(context)
		self.assertEqual(context.title, "New ASN")
		self.assertEqual(context.single_errors, [])

	def test_parse_single_rows_collects_missing_required_fields(self):
		class _FakeForm:
			def __init__(self):
				self.data = {
					"single_manual_purchase_order": [""],
					"single_manual_sr_no": ["1"],
					"single_manual_item_code": [""],
					"single_manual_uom": ["Nos"],
					"single_manual_qty": [""],
					"single_manual_rate": ["10"],
				}

			def getlist(self, fieldname):
				return self.data.get(fieldname, [])

		request = SimpleNamespace(form=_FakeForm())
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._parse_single_rows()

		self.assertEqual(ctx.exception.errors[0]["field"], "row")
		self.assertIn("purchase_order", ctx.exception.errors[0]["message"])

	def test_parse_single_rows_collects_invalid_qty_and_rate(self):
		class _FakeForm:
			def __init__(self):
				self.data = {
					"single_manual_purchase_order": ["PO-0001", "PO-0001"],
					"single_manual_sr_no": ["1", "2"],
					"single_manual_item_code": ["ITEM-001", "ITEM-002"],
					"single_manual_uom": ["Nos", "Nos"],
					"single_manual_qty": ["0", "1"],
					"single_manual_rate": ["10", "-1"],
				}

			def getlist(self, fieldname):
				return self.data.get(fieldname, [])

		request = SimpleNamespace(form=_FakeForm())
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._parse_single_rows()

		fields = [error["field"] for error in ctx.exception.errors]
		self.assertEqual(fields, ["qty", "rate"])

	def test_parse_bulk_csv_rows_returns_empty_without_file(self):
		with patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace(files={})):
			self.assertEqual(asn_new._parse_bulk_csv_rows(), [])

	def test_parse_bulk_csv_rows_rejects_invalid_utf8(self):
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(b"\xff\xfe"))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._parse_bulk_csv_rows()

		self.assertEqual(ctx.exception.errors[0]["field"], "items_csv")

	def test_parse_bulk_csv_rows_collects_missing_required_fields(self):
		csv_content = _bulk_csv_content(
			"INV-1,"
			f"{_test_dates()['supplier_invoice_date']},{_test_dates()['expected_delivery_date']},"
			f"LR-1,{_test_dates()['lr_date']},TR-1,,,250,PO-0001,,ITEM-001,10,25"
		)
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError) as ctx,
		):
			asn_new._parse_bulk_csv_rows()

		self.assertEqual(ctx.exception.errors[0]["field"], "row")
		self.assertIn("sr_no", ctx.exception.errors[0]["message"])

	def test_insert_and_submit_asn_sets_ignore_permissions_and_submits(self):
		fake_asn = SimpleNamespace(
			flags=SimpleNamespace(), insert=lambda **_kwargs: None, submit=lambda: None
		)
		with patch("asn_module.templates.pages.asn_new.frappe.get_doc", return_value=fake_asn) as get_doc:
			result = asn_new._insert_and_submit_asn(
				supplier="Supp-001",
				header={
					"supplier_invoice_no": "INV-1",
					"supplier_invoice_date": _test_dates()["supplier_invoice_date"],
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
					"supplier_invoice_amount": 100,
				},
				items=[{"item_code": "ITEM-001", "qty": 1}],
			)

		self.assertIs(result, fake_asn)
		self.assertTrue(fake_asn.flags.ignore_permissions)
		self.assertEqual(get_doc.call_args.args[0]["supplier_invoice_amount"], 100)

	def test_request_supplier_invoice_amount_valid(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": "100"}),
		):
			result = asn_new._request_supplier_invoice_amount()
		self.assertEqual(result, 100.0)

	def test_request_supplier_invoice_amount_negative_raises(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": "-10"}),
			self.assertRaises(PortalValidationError),
		):
			asn_new._request_supplier_invoice_amount()

	def test_request_supplier_invoice_amount_empty_raises(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": ""}),
			self.assertRaises(PortalValidationError),
		):
			asn_new._request_supplier_invoice_amount()

	def test_default_asn_route_format(self):
		route = asn_new._default_asn_route("ASN-001")
		self.assertTrue(route.startswith("asn/"))

	def test_get_context_rejects_non_supplier(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="GET", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="non-supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value=None),
			self.assertRaises(frappe.PermissionError),
		):
			asn_new.get_context(context)
