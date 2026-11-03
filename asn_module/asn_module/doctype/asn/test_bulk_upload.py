from contextlib import contextmanager
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn import bulk_upload
from asn_module.templates.pages.asn_new_services import (
	BULK_CSV_HEADERS,
	ParsedBulkRow,
	PortalValidationError,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates
from asn_module.utils.test_setup import before_tests


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


_BULK_UPLOAD_MODULE = "asn_module.asn_module.doctype.asn.bulk_upload"


def _allow_desk_permissions():
	"""Patch the bulk-upload module's permission check to allow everything."""
	return patch(f"{_BULK_UPLOAD_MODULE}.frappe.has_permission", return_value=True)


class TestDeskBulkASNUpload(FrappeTestCase):
	def test_get_bulk_csv_headers_requires_permission_and_returns_headers(self):
		with _allow_desk_permissions():
			self.assertEqual(bulk_upload.get_bulk_csv_headers(), BULK_CSV_HEADERS)

	def test_create_from_csv_file_requires_csv_file(self):
		with (
			_allow_desk_permissions(),
			patch("asn_module.asn_module.doctype.asn.bulk_upload._read_file_content") as read_file_content,
			self.assertRaises(frappe.ValidationError) as ctx,
		):
			bulk_upload.create_from_csv_file(file_url=" ", supplier="Supp-001")

		read_file_content.assert_not_called()
		self.assertIn("Upload a CSV file", str(ctx.exception))

	def test_create_from_csv_file_requires_supplier(self):
		with (
			_allow_desk_permissions(),
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
			_allow_desk_permissions(),
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
			_allow_desk_permissions(),
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
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_all", return_value=["F-1"]),
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_doc", return_value=file_doc),
			_allow_desk_permissions(),
		):
			self.assertEqual(bulk_upload._read_file_content("/private/files/asn.csv"), b"csv-bytes")

	def test_read_file_content_encodes_text(self):
		file_doc = frappe._dict(get_content=lambda: "csv-text")
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_all", return_value=["F-1"]),
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_doc", return_value=file_doc),
			_allow_desk_permissions(),
		):
			self.assertEqual(bulk_upload._read_file_content("/private/files/asn.csv"), b"csv-text")

	def test_read_file_content_without_read_permission_raises_permission_error(self):
		file_doc = frappe._dict(get_content=Mock(return_value=b"secret-cell-content"))
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_all", return_value=["F-1"]),
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_doc", return_value=file_doc),
			patch(
				f"{_BULK_UPLOAD_MODULE}.frappe.has_permission",
				return_value=False,
			),
			self.assertRaises(frappe.PermissionError) as ctx,
		):
			bulk_upload._read_file_content("/private/files/secret.csv")

		file_doc.get_content.assert_not_called()
		self.assertNotIn("secret-cell-content", str(ctx.exception))
		self.assertNotIn("/private/files/secret.csv", str(ctx.exception))

	def test_read_file_content_uses_the_readable_duplicate(self):
		"""Several File rows can share one URL; use the one the caller may read."""
		unreadable = frappe._dict(get_content=Mock(side_effect=AssertionError("must not read")))
		readable = frappe._dict(get_content=lambda: b"owned-csv")
		docs = {"F-old": unreadable, "F-new": readable}
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_all", return_value=["F-new", "F-old"]),
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_doc", side_effect=lambda dt, name: docs[name]),
			patch(
				f"{_BULK_UPLOAD_MODULE}.frappe.has_permission",
				side_effect=lambda dt, ptype, doc: doc is readable,
			),
		):
			self.assertEqual(bulk_upload._read_file_content("/private/files/asn.csv"), b"owned-csv")

	def test_read_file_content_raises_clear_error_for_missing_file(self):
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.frappe.get_all", return_value=[]),
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


FILE_PERM_USER = "asn.bulk.upload.file.perm@asn-module.test"
PORTAL_ROLE_USER = "asn.bulk.upload.portal.role@asn-module.test"


@contextmanager
def _as_user(email: str):
	previous = frappe.session.user
	frappe.set_user(email)
	try:
		yield
	finally:
		frappe.set_user(previous)


class TestDeskBulkUploadFilePermission(FrappeTestCase):
	"""Issue #65 regression: the desk bulk-upload endpoint must check read permission
	on the referenced File before reading its content, using the real Frappe permission
	engine (a private File owned by someone else, a plain enabled User).
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		if not frappe.db.exists("User", FILE_PERM_USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": FILE_PERM_USER,
					"first_name": "ASN Bulk Upload Test",
					"send_welcome_email": 0,
					"enabled": 1,
				}
			)
			user.insert(ignore_permissions=True)
		if not frappe.db.exists("User", PORTAL_ROLE_USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": PORTAL_ROLE_USER,
					"first_name": "ASN Bulk Upload Portal Test",
					"send_welcome_email": 0,
					"enabled": 1,
					"roles": [{"role": "Supplier"}],
				}
			)
			user.insert(ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _make_csv_file(self, *, file_name, content, is_private, owner=None):
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"content": content,
				"is_private": is_private,
			}
		)
		file_doc.insert(ignore_permissions=True)
		if owner and file_doc.owner != owner:
			frappe.db.set_value("File", file_doc.name, "owner", owner, update_modified=False)
			file_doc.reload()
		return file_doc

	def test_create_from_csv_file_without_file_read_permission_raises_permission_error(self):
		secret = "SECRET-CELL-78945"
		file_doc = self._make_csv_file(
			file_name=f"secret-{frappe.generate_hash(length=6)}.csv",
			content=f"col\n{secret}",
			is_private=1,
		)
		with (
			patch.object(bulk_upload, "_require_desk_bulk_permissions"),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.parse_bulk_csv_content"
			) as parse_bulk_csv_content,
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.create_bulk_asns_for_supplier",
				return_value=["ASN-0001"],
			),
			_as_user(FILE_PERM_USER),
			self.assertRaises(frappe.PermissionError) as ctx,
		):
			bulk_upload.create_from_csv_file(file_url=file_doc.file_url, supplier="Supp-001")

		parse_bulk_csv_content.assert_not_called()
		self.assertNotIn(secret, str(ctx.exception))
		self.assertNotIn(file_doc.file_name, str(ctx.exception))
		self.assertNotIn(file_doc.file_url, str(ctx.exception))

	def test_create_from_csv_file_with_file_read_permission_succeeds(self):
		file_doc = self._make_csv_file(
			file_name=f"owned-{frappe.generate_hash(length=6)}.csv",
			content="csv-text",
			is_private=1,
			owner=FILE_PERM_USER,
		)
		rows = [_bulk_row()]
		with (
			patch.object(bulk_upload, "_require_desk_bulk_permissions"),
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.parse_bulk_csv_content",
				return_value=rows,
			) as parse_bulk_csv_content,
			patch(
				"asn_module.asn_module.doctype.asn.bulk_upload.create_bulk_asns_for_supplier",
				return_value=["ASN-0001"],
			) as create_bulk_asns_for_supplier,
			_as_user(FILE_PERM_USER),
		):
			result = bulk_upload.create_from_csv_file(file_url=file_doc.file_url, supplier="Supp-001")

		parse_bulk_csv_content.assert_called_once_with(b"csv-text")
		create_bulk_asns_for_supplier.assert_called_once_with("Supp-001", rows)
		self.assertEqual(result, {"asn_names": ["ASN-0001"], "created_count": 1})

	def test_portal_role_user_is_rejected_at_the_desk_permission_gate(self):
		"""A Supplier-role (portal) user never reaches the file check: the ASN
		create/submit gate rejects them first, so no portal-path test is needed."""
		with (
			patch(f"{_BULK_UPLOAD_MODULE}.parse_bulk_csv_content") as parse_bulk_csv_content,
			patch(f"{_BULK_UPLOAD_MODULE}._read_file_content") as read_file_content,
			_as_user(PORTAL_ROLE_USER),
			self.assertRaises(frappe.PermissionError),
		):
			bulk_upload.create_from_csv_file(file_url="/private/files/x.csv", supplier="Supp-001")

		read_file_content.assert_not_called()
		parse_bulk_csv_content.assert_not_called()
