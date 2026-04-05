from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages import asn_new
from asn_module.templates.pages.asn_new_services import (
	ParsedSingleRow,
	ParsedBulkRow,
	PortalValidationError,
	resolve_po_item,
	validate_no_duplicate_po_sr_no,
)


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

	def test_parse_bulk_csv_rows_accepts_strict_template(self):
		csv_content = b"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,purchase_order,sr_no,item_code,qty,rate\nINV-1,2026-04-05,2026-04-06,LR-1,2026-04-05,TR-1,PO-0001,1,ITEM-001,10,25\n"
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

	def test_parse_bulk_csv_rows_rejects_header_order_mismatch(self):
		csv_content = b"supplier_invoice_no,purchase_order,sr_no,item_code,qty,rate\nINV-1,PO-0001,1,ITEM-001,10,25\n"
		request = SimpleNamespace(
			files={"bulk_items_csv": SimpleNamespace(filename="items.csv", stream=BytesIO(csv_content))}
		)
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			self.assertRaises(PortalValidationError),
		):
			asn_new._parse_bulk_csv_rows()

	def test_get_context_rejects_invalid_mode_with_417(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="POST", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"mode": "invalid"}),
			patch("asn_module.templates.pages.asn_new.frappe.session", SimpleNamespace(user="supplier@example.com")),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]),
			patch("asn_module.templates.pages.asn_new.frappe.local", SimpleNamespace(response={})),
		):
			asn_new.get_context(context)
		self.assertEqual(context.active_tab, "single")
		self.assertTrue(context.single_errors)
		self.assertEqual(context.single_errors[0]["field"], "mode")

	def test_service_rejects_duplicate_po_sr_no_in_same_invoice_group(self):
		rows = [
			ParsedBulkRow(
				row_number=2,
				supplier_invoice_no="INV-1",
				supplier_invoice_date="2026-04-05",
				expected_delivery_date="2026-04-06",
				lr_no="",
				lr_date="",
				transporter_name="",
				purchase_order="PO-0001",
				sr_no="10",
				item_code="ITEM-001",
				qty=1,
				rate=10,
			),
			ParsedBulkRow(
				row_number=3,
				supplier_invoice_no="INV-1",
				supplier_invoice_date="2026-04-05",
				expected_delivery_date="2026-04-06",
				lr_no="",
				lr_date="",
				transporter_name="",
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
			ParsedSingleRow(row_number=1, purchase_order="PO-0001", sr_no="1", item_code="ITEM-001", uom="Nos", qty=1, rate=10),
			ParsedSingleRow(row_number=2, purchase_order="PO-0001", sr_no="1", item_code="ITEM-001", uom="Nos", qty=1, rate=10),
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

	def test_create_single_asn_rejects_cumulative_qty_exceeding_remaining(self):
		rows = [
			ParsedSingleRow(row_number=1, purchase_order="PO-0001", sr_no="1", item_code="ITEM-001", uom="Nos", qty=6, rate=10),
			ParsedSingleRow(row_number=2, purchase_order="PO-0001", sr_no="2", item_code="ITEM-002", uom="Nos", qty=5, rate=10),
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
