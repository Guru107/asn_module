from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.scan_codes import (
	format_scan_code_for_display,
	get_or_create_scan_code,
	get_scan_code_doc,
	normalize_scan_code,
	record_successful_scan,
	validate_scan_code_row,
	verify_registry_row_points_to_existing_source,
)


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


class TestGetOrCreateScanCode(FrappeTestCase):
	def test_creates_new_scan_code(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-001")
		self.assertTrue(name)
		doc = frappe.get_doc("Scan Code", name)
		self.assertEqual(doc.action_key, "create_purchase_receipt")
		self.assertEqual(doc.source_doctype, "ASN")
		self.assertEqual(doc.source_name, "ASN-TEST-001")
		self.assertEqual(doc.status, "Active")

	def test_returns_existing_active(self):
		first = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-002")
		second = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-002")
		self.assertEqual(first, second)

	def test_rejects_empty_action_key(self):
		with self.assertRaises(frappe.ValidationError):
			get_or_create_scan_code("", "ASN", "ASN-TEST-003")


class TestGetScanCodeDoc(FrappeTestCase):
	def test_found(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-010")
		doc = get_scan_code_doc(name)
		self.assertIsNotNone(doc)
		self.assertEqual(doc.name, name)

	def test_not_found(self):
		result = get_scan_code_doc("NONEXISTENT-CODE")
		self.assertIsNone(result)

	def test_normalized_lookup(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-011")
		doc = get_scan_code_doc(f"  {name[:4]}-{name[4:]}  ")
		self.assertIsNotNone(doc)


class TestValidateScanCodeRow(FrappeTestCase):
	def _make_scan_code_doc(self, status="Active", expires_on=None):
		name = get_or_create_scan_code(
			"create_purchase_receipt", "ASN", f"ASN-VLD-{frappe.generate_hash(length=6)}"
		)
		if status != "Active":
			frappe.db.set_value("Scan Code", name, "status", status, update_modified=False)
		if expires_on is not None:
			frappe.db.set_value("Scan Code", name, "expires_on", expires_on, update_modified=False)
		return frappe.get_doc("Scan Code", name)

	def test_active_ok(self):
		doc = self._make_scan_code_doc(status="Active")
		validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_blocked(self):
		doc = self._make_scan_code_doc(status="Used")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_rescan_safe_ok(self):
		doc = self._make_scan_code_doc(status="Used")
		validate_scan_code_row(doc, "confirm_putaway")

	def test_revoked_blocked(self):
		doc = self._make_scan_code_doc(status="Revoked")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_expired_blocked(self):
		doc = self._make_scan_code_doc(status="Expired")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_expiry_date_in_past_blocked(self):
		doc = self._make_scan_code_doc(status="Active", expires_on="2000-01-01")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")


class TestRecordSuccessfulScan(FrappeTestCase):
	def test_increments_count(self):
		name = get_or_create_scan_code(
			"create_purchase_receipt", "ASN", f"ASN-REC-{frappe.generate_hash(length=6)}"
		)
		record_successful_scan(name, "create_purchase_receipt")
		count = frappe.db.get_value("Scan Code", name, "scan_count")
		self.assertEqual(count, 1)

	def test_sets_used_for_non_rescan_safe(self):
		name = get_or_create_scan_code(
			"create_purchase_receipt", "ASN", f"ASN-REC2-{frappe.generate_hash(length=6)}"
		)
		record_successful_scan(name, "create_purchase_receipt")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Used")

	def test_stays_active_for_rescan_safe(self):
		name = get_or_create_scan_code("confirm_putaway", "ASN", f"ASN-REC3-{frappe.generate_hash(length=6)}")
		record_successful_scan(name, "confirm_putaway")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Active")


class TestVerifyRegistryRowPointsToExistingSource(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from asn_module.utils.test_setup import before_tests

		before_tests()

	def test_valid_source_returns_true(self):
		from asn_module.asn_module.doctype.asn.test_asn import (
			create_purchase_order,
			make_test_asn,
		)

		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		doc = frappe.get_doc("Scan Code", name)
		self.assertTrue(verify_registry_row_points_to_existing_source(doc))

	def test_missing_source_returns_false(self):
		name = get_or_create_scan_code(
			"create_purchase_receipt",
			"ASN",
			f"NONEXISTENT-{frappe.generate_hash(length=6)}",
		)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))

	def test_missing_doctype_returns_false(self):
		name = get_or_create_scan_code(
			"create_purchase_receipt", "ASN", f"ASN-VRFY2-{frappe.generate_hash(length=6)}"
		)
		frappe.db.set_value("Scan Code", name, "source_doctype", "FakeDocType", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))
