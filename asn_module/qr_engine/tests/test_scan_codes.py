from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.scan_codes import (
	_random_scan_code_value,
	format_scan_code_for_display,
	get_or_create_scan_code,
	get_scan_code_doc,
	normalize_scan_code,
	record_successful_scan,
	validate_scan_code_row,
	verify_registry_row_points_to_existing_source,
)


class _ScanCodeTestMixin:
	@classmethod
	def _create_real_asn(cls):
		from asn_module.asn_module.doctype.asn.test_asn import (
			create_purchase_order,
			make_test_asn,
		)
		from asn_module.utils.test_setup import before_tests
		before_tests()
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		cls._asn = asn
		cls._asn_name = asn.name

	def _make_scan_code_direct(self, *, action_key, source_doctype, source_name, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": _random_scan_code_value(),
				"action_key": action_key,
				"source_doctype": source_doctype,
				"source_name": source_name,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
		return doc.name


class TestFormatScanCodeForDisplay(FrappeTestCase):
	def test_empty_code_returns_empty(self):
		self.assertEqual(format_scan_code_for_display(""), "")

	def test_short_code_unchanged(self):
		self.assertEqual(format_scan_code_for_display("AB"), "AB")

	def test_exact_group_length(self):
		self.assertEqual(format_scan_code_for_display("ABCD"), "ABCD")

	def test_long_code_grouped(self):
		result = format_scan_code_for_display("ABCDEFGHIJKLMNOP")
		self.assertEqual(result, "ABCD-EFGH-IJKL-MNOP")

	def test_odd_length_code(self):
		result = format_scan_code_for_display("ABCDEFGHI")
		self.assertEqual(result, "ABCD-EFGH-I")


class TestNormalizeScanCode(FrappeTestCase):
	def test_none_returns_empty(self):
		self.assertEqual(normalize_scan_code(None), "")

	def test_strips_dashes(self):
		self.assertEqual(normalize_scan_code("AB-CD-EF"), "ABCDEF")

	def test_strips_spaces(self):
		self.assertEqual(normalize_scan_code("AB CD EF"), "ABCDEF")

	def test_uppercases(self):
		self.assertEqual(normalize_scan_code("abcdef"), "ABCDEF")


class TestGetOrCreateScanCode(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_rejects_empty_action_key(self):
		with self.assertRaises(frappe.ValidationError):
			get_or_create_scan_code("", "ASN", self._asn_name)

	def test_creates_new_scan_code(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		self.assertTrue(frappe.db.exists("Scan Code", name))

	def test_returns_existing_active(self):
		first = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		second = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		self.assertEqual(first, second)


class TestGetScanCodeDoc(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_not_found(self):
		with patch("asn_module.qr_engine.scan_codes.frappe.has_permission", return_value=True):
			result = get_scan_code_doc("NONEXISTENT-CODE-XYZ")
		self.assertIsNone(result)

	def test_found(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		with patch("asn_module.qr_engine.scan_codes.frappe.has_permission", return_value=True):
			doc = get_scan_code_doc(frappe.db.get_value("Scan Code", name, "scan_code"))
		self.assertIsNotNone(doc)
		self.assertEqual(doc.name, name)

	def test_normalized_lookup(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		raw_code = frappe.db.get_value("Scan Code", name, "scan_code")
		with patch("asn_module.qr_engine.scan_codes.frappe.has_permission", return_value=True):
			doc = get_scan_code_doc(normalize_scan_code(raw_code))
		self.assertIsNotNone(doc)
		self.assertEqual(doc.name, name)


class TestRecordSuccessfulScan(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_increments_count(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		record_successful_scan(name, "create_purchase_receipt")
		count = frappe.db.get_value("Scan Code", name, "scan_count")
		self.assertEqual(count, 1)

	def test_sets_used_for_non_rescan_safe(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		record_successful_scan(name, "create_purchase_receipt")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Used")

	def test_stays_active_for_rescan_safe(self):
		name = get_or_create_scan_code("confirm_putaway", "ASN", self._asn_name)
		record_successful_scan(name, "confirm_putaway")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Active")


class TestValidateScanCodeRow(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_active_ok(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		doc = frappe.get_doc("Scan Code", name)
		validate_scan_code_row(doc, "create_purchase_receipt")

	def test_revoked_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Revoked", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_expired_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Expired", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_rescan_safe_ok(self):
		name = get_or_create_scan_code("confirm_putaway", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		validate_scan_code_row(doc, "confirm_putaway")

	def test_expiry_date_in_past_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "expires_on", "2000-01-01", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")


class TestVerifyRegistryRowPointsToExistingSource(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_valid_source_returns_true(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		doc = frappe.get_doc("Scan Code", name)
		self.assertTrue(verify_registry_row_points_to_existing_source(doc))

	def test_missing_source_returns_false(self):
		name = self._make_scan_code_direct(
			action_key="create_purchase_receipt",
			source_doctype="ASN",
			source_name="NONEXISTENT-" + frappe.generate_hash(length=6),
		)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))

	def test_missing_doctype_returns_false(self):
		name = self._make_scan_code_direct(
			action_key="create_purchase_receipt",
			source_doctype="FakeDocType",
			source_name="FAKE-" + frappe.generate_hash(length=6),
		)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))


	def test_empty_source_name_returns_false(self):
		name = self._make_scan_code_direct(
			action_key="create_purchase_receipt",
			source_doctype="ASN",
			source_name="",
		)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))

	def test_exception_during_db_check_returns_false(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		doc = frappe.get_doc("Scan Code", name)
		with patch("asn_module.qr_engine.scan_codes.frappe.db.exists", side_effect=Exception("db error")):
			self.assertFalse(verify_registry_row_points_to_existing_source(doc))

