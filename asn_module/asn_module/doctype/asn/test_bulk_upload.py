from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn import bulk_upload
from asn_module.templates.pages.asn_new_services import (
	BULK_CSV_HEADERS,
	ParsedBulkRow,
	PortalValidationError,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def _test_dates():
	return get_fiscal_year_test_dates()


def _bulk_row(**overrides):
	defaults = dict(
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
	)
	defaults.update(overrides)
	return ParsedBulkRow(**defaults)


class TestDeskBulkASNUpload(FrappeTestCase):
	def test_get_bulk_csv_headers_requires_permission_and_returns_headers(self):
		with patch(
			"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
			return_value=True,
		):
			self.assertEqual(bulk_upload.get_bulk_csv_headers(), BULK_CSV_HEADERS)

	def test_create_from_csv_file_requires_csv_file(self):
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
				return_value=True,
			),
			patch("asn_module.asn_module.doctype.asn.bulk_upload._read_file_content") as read_file_content,
			self.assertRaises(frappe.ValidationError) as ctx,
		):
			bulk_upload.create_from_csv_file(file_url=" ", supplier="Supp-001")

		read_file_content.assert_not_called()
		self.assertIn("Upload a CSV file", str(ctx.exception))

	def test_create_from_csv_file_requires_supplier(self):
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
				return_value=True,
			),
			patch("asn_module.asn_module.doctype.asn.bulk_upload._read_file_content") as read_file_content,
			self.assertRaises(frappe.ValidationError) as ctx,
		):
			bulk_upload.create_from_csv_file(file_url="/private/files/asn.csv", supplier=" ")

		read_file_content.assert_not_called()
		self.assertIn("Supplier is required", str(ctx.exception))

	def test_create_from_csv_file_requires_create_and_submit_permission(self):
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
				side_effect=lambda doctype, ptype: doctype == "ASN" and ptype == "create",
			),
			patch("asn_module.asn_module.doctype.asn.bulk_upload._read_file_content") as read_file_content,
			self.assertRaises(frappe.PermissionError),
		):
			bulk_upload.create_from_csv_file(file_url="/private/files/asn.csv", supplier="Supp-001")

		read_file_content.assert_not_called()

	def test_create_from_csv_file_returns_created_asn_names(self):
		rows = [_bulk_row()]
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
				return_value=True,
			),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload._read_file_content",
				return_value=b"csv",
			),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.parse_bulk_csv_content",
				return_value=rows,
			) as parse_bulk_csv_content,
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.create_bulk_asns_for_supplier",
				return_value=["ASN-0001", "ASN-0002"],
			) as create_bulk_asns_for_supplier,
		):
			result = bulk_upload.create_from_csv_file(file_url="/private/files/asn.csv", supplier="Supp-001")

		parse_bulk_csv_content.assert_called_once_with(b"csv")
		create_bulk_asns_for_supplier.assert_called_once_with("Supp-001", rows)
		self.assertEqual(result, {"asn_names": ["ASN-0001", "ASN-0002"], "created_count": 2})

	def test_create_from_csv_file_formats_portal_validation_errors_for_desk(self):
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.has_permission",
				return_value=True,
			),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload._read_file_content",
				return_value=b"csv",
			),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.parse_bulk_csv_content",
				side_effect=PortalValidationError(
					[
						{
							"row_number": 2,
							"invoice_no": "INV-1",
							"field": "qty",
							"message": "Row 2: qty must be greater than 0.",
						}
					]
				),
			),
			self.assertRaises(frappe.ValidationError) as ctx,
		):
			bulk_upload.create_from_csv_file(file_url="/private/files/asn.csv", supplier="Supp-001")

		self.assertIn("Row 2: qty must be greater than 0.", str(ctx.exception))

	def test_read_file_content_returns_bytes(self):
		file_doc = frappe._dict(get_content=lambda: b"csv-bytes")
		with patch("asn_module.asn_module.doctype.asn.bulk_upload.frappe.get_doc", return_value=file_doc):
			self.assertEqual(bulk_upload._read_file_content("/private/files/asn.csv"), b"csv-bytes")

	def test_read_file_content_encodes_text(self):
		file_doc = frappe._dict(get_content=lambda: "csv-text")
		with patch("asn_module.asn_module.doctype.asn.bulk_upload.frappe.get_doc", return_value=file_doc):
			self.assertEqual(bulk_upload._read_file_content("/private/files/asn.csv"), b"csv-text")

	def test_read_file_content_raises_clear_error_for_missing_file(self):
		with (
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.frappe.get_doc",
				side_effect=frappe.DoesNotExistError("missing"),
			),
			self.assertRaises(frappe.ValidationError) as ctx,
		):
			bulk_upload._read_file_content("/private/files/missing.csv")

		self.assertIn("/private/files/missing.csv", str(ctx.exception))
		self.assertIn("re-upload the CSV", str(ctx.exception))

	def test_format_validation_errors_uses_fallback_message(self):
		self.assertEqual(
			bulk_upload._format_validation_errors([{"message": " "}]),
			"Bulk upload failed. No ASNs created.",
		)
