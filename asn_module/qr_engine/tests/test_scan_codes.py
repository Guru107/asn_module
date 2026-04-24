import importlib
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from asn_module.qr_engine.scan_codes import (
	SCAN_CODE_ALPHABET,
	SCAN_CODE_LENGTH,
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

	def test_short_code_is_uppercased(self):
		self.assertEqual(format_scan_code_for_display("ab"), "AB")

	def test_removes_spaces_and_dashes_without_grouping(self):
		self.assertEqual(format_scan_code_for_display("ab cd-ef"), "ABCDEF")

	def test_long_code_is_not_grouped(self):
		result = format_scan_code_for_display("ABCDEFGHIJKLMNOP")
		self.assertEqual(result, "ABCDEFGHIJKLMNOP")

	def test_odd_length_code_is_not_grouped(self):
		result = format_scan_code_for_display("ABCDEFGHI")
		self.assertEqual(result, "ABCDEFGHI")


class TestNormalizeScanCode(FrappeTestCase):
	def test_none_returns_empty(self):
		self.assertEqual(normalize_scan_code(None), "")

	def test_rejects_wrong_length(self):
		self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQ"), "")
		self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQRST"), "")

	def test_rejects_invalid_characters(self):
		self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQ0"), "")
		self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQI"), "")

	def test_rejects_dashes(self):
		self.assertEqual(normalize_scan_code("ABCD-EFGH-JKLM-NPQR"), "")

	def test_accepts_valid_16_char_code_and_normalizes(self):
		self.assertEqual(normalize_scan_code("  abcd efgh jklm npqr  "), "ABCDEFGHJKLMNPQR")


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
		self.assertEqual(len(name), SCAN_CODE_LENGTH)
		self.assertTrue(all(ch in SCAN_CODE_ALPHABET for ch in name))
		self.assertEqual(normalize_scan_code(name), name)
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
		frappe.db.set_value("Scan Code", name, "expires_on", add_days(today(), -1), update_modified=False)
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


class TestGetOrCreateScanCodeCanonicalReuse(TestCase):
	def test_invalid_active_row_is_not_reused(self):
		doc = MagicMock()
		doc.name = "ABCDEFGHJKLMNPQ2"
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = "ABCD-EFGH-JKLM-NPQR"
		fake_frappe.db.exists.return_value = False
		fake_frappe.get_doc.return_value = doc

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch(
				"asn_module.qr_engine.scan_codes._random_scan_code_value",
				return_value="ABCDEFGHJKLMNPQ2",
			),
		):
			result = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-001")

		self.assertEqual(result, "ABCDEFGHJKLMNPQ2")
		self.assertEqual(len(result), SCAN_CODE_LENGTH)
		self.assertTrue(all(ch in SCAN_CODE_ALPHABET for ch in result))
		self.assertEqual(normalize_scan_code(result), result)
		fake_frappe.db.get_value.assert_called_once()
		fake_frappe.db.exists.assert_called_once_with("Scan Code", "ABCDEFGHJKLMNPQ2")
		fake_frappe.get_doc.assert_called_once()

	def test_retries_on_collision_then_creates(self):
		doc = MagicMock()
		doc.name = "ABCDEFGHJKLMNPQ3"
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = None
		fake_frappe.db.exists.side_effect = [True, False]
		fake_frappe.get_doc.return_value = doc

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch(
				"asn_module.qr_engine.scan_codes._random_scan_code_value",
				side_effect=["ABCDEFGHJKLMNPQ2", "ABCDEFGHJKLMNPQ3"],
			),
		):
			result = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-003")

		self.assertEqual(result, "ABCDEFGHJKLMNPQ3")
		self.assertEqual(fake_frappe.db.exists.call_count, 2)

	def test_raises_when_unique_code_not_available(self):
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = None
		fake_frappe.db.exists.return_value = True
		fake_frappe.throw.side_effect = RuntimeError("exhausted")

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch("asn_module.qr_engine.scan_codes._random_scan_code_value", return_value="ABCDEFGHJKLMNPQ2"),
			self.assertRaises(RuntimeError),
		):
			get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-004")


class TestScanCodeModuleLevelCoverage(TestCase):
	def test_get_scan_code_length_and_reload_module(self):
		import asn_module.qr_engine.scan_codes as scan_codes_module

		self.assertEqual(scan_codes_module.get_scan_code_length(), SCAN_CODE_LENGTH)
		reloaded = importlib.reload(scan_codes_module)
		self.assertEqual(reloaded.SCAN_CODE_ALPHABET, SCAN_CODE_ALPHABET)


class TestValidateScanCodeRowExtraBranches(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_invalid_non_active_status_is_rejected(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Paused", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_newly_created_scan_code_is_canonical_16_chars(self):
		doc = MagicMock()
		doc.name = "ABCDEFGHJKLMNPQ2"
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = None
		fake_frappe.db.exists.return_value = False
		fake_frappe.get_doc.return_value = doc

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch(
				"asn_module.qr_engine.scan_codes._random_scan_code_value",
				return_value="ABCDEFGHJKLMNPQ2",
			),
		):
			result = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-002")

		self.assertEqual(result, "ABCDEFGHJKLMNPQ2")
		self.assertEqual(len(result), SCAN_CODE_LENGTH)
		self.assertTrue(all(ch in SCAN_CODE_ALPHABET for ch in result))
		self.assertEqual(normalize_scan_code(result), result)
		fake_frappe.db.get_value.assert_called_once()
		fake_frappe.db.exists.assert_called_once_with("Scan Code", "ABCDEFGHJKLMNPQ2")
		fake_frappe.get_doc.assert_called_once()
