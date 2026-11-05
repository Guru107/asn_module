from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.scan_codes import (
	SCAN_CODE_ALPHABET,
	SCAN_CODE_LENGTH,
	_random_scan_code_value,
	format_scan_code_for_display,
	get_or_create_scan_code,
	get_scan_code_doc,
	get_scan_code_length,
	normalize_scan_code,
	purge_scan_codes_for_source,
	purge_scan_registry_on_trash,
	reactivate_scan_code,
	reactivate_upstream_scan_codes_for_trashed_document,
	record_successful_scan,
	resolve_scan_code_for_attachment,
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
	def test_get_scan_code_length_returns_canonical_length(self):
		self.assertEqual(get_scan_code_length(), SCAN_CODE_LENGTH)

	def test_random_scan_code_value_uses_canonical_alphabet_and_length(self):
		value = _random_scan_code_value()
		self.assertEqual(len(value), SCAN_CODE_LENGTH)
		self.assertTrue(all(ch in SCAN_CODE_ALPHABET for ch in value))

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

	def test_resolve_reuses_used_row_for_attachment(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		self.assertEqual(
			resolve_scan_code_for_attachment("create_purchase_receipt", "ASN", self._asn_name),
			name,
		)

	def test_resolve_creates_when_no_registry_row(self):
		code = resolve_scan_code_for_attachment("create_purchase_invoice", "ASN", self._asn_name)
		self.assertEqual(len(code), SCAN_CODE_LENGTH)
		self.assertTrue(frappe.db.exists("Scan Code", code))

	def test_resolve_rejects_missing_registration_fields(self):
		with self.assertRaises(frappe.ValidationError):
			resolve_scan_code_for_attachment("", "ASN", self._asn_name)


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

	def test_sets_used_after_scan(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		record_successful_scan(name, "create_purchase_receipt")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Used")


class TestValidateScanCodeRow(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_active_ok(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		doc = frappe.get_doc("Scan Code", name)
		validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_unknown_status_blocked(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Suspended", update_modified=False)
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


class TestPurgeScanRegistryOnTrash(FrappeTestCase, _ScanCodeTestMixin):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_real_asn()

	def test_purge_scan_codes_for_source_deletes_matching_rows(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		self.assertTrue(frappe.db.exists("Scan Code", name))
		purge_scan_codes_for_source("ASN", self._asn_name)
		self.assertFalse(frappe.db.exists("Scan Code", name))

	def test_purge_scan_registry_on_trash_skips_submitted_documents(self):
		with patch("asn_module.qr_engine.scan_codes.purge_scan_codes_for_source") as purge_codes:
			with patch("asn_module.qr_engine.scan_codes.purge_scan_logs_for_document") as purge_logs:
				purge_scan_registry_on_trash(SimpleNamespace(doctype="Gate Pass", name="GP-1", docstatus=1))
		purge_codes.assert_not_called()
		purge_logs.assert_not_called()

	def test_purge_scan_registry_on_trash_skips_unrelated_doctypes_without_registry_rows(self):
		with patch("asn_module.qr_engine.scan_codes.purge_scan_codes_for_source") as purge_codes:
			with patch(
				"asn_module.qr_engine.scan_codes.reactivate_upstream_scan_codes_for_trashed_document"
			) as reactivate:
				purge_scan_registry_on_trash(SimpleNamespace(doctype="Customer", name="Cust-1", docstatus=0))
		purge_codes.assert_not_called()
		reactivate.assert_not_called()

	def test_purge_scan_registry_on_trash_removes_codes_for_draft_documents(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		purge_scan_registry_on_trash(SimpleNamespace(doctype="ASN", name=self._asn_name, docstatus=0))
		self.assertFalse(frappe.db.exists("Scan Code", name))

	def test_purge_scan_registry_on_trash_removes_codes_for_cancelled_documents(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Voided", update_modified=False)
		purge_scan_registry_on_trash(SimpleNamespace(doctype="ASN", name=self._asn_name, docstatus=2))
		self.assertFalse(frappe.db.exists("Scan Code", name))

	def test_reactivate_scan_code_sets_used_rows_active(self):
		name = get_or_create_scan_code("create_gate_pass_from_asn", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		reactivate_scan_code("create_gate_pass_from_asn", "ASN", self._asn_name)
		self.assertEqual(frappe.db.get_value("Scan Code", name, "status"), "Active")

	def test_purge_scan_registry_reactivates_asn_code_before_logs_are_removed(self):
		code = get_or_create_scan_code("create_gate_pass_from_asn", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		pr = SimpleNamespace(
			doctype="Purchase Receipt", name="PR-REACTIVATE-1", docstatus=0, asn=self._asn_name
		)
		with patch(
			"asn_module.qr_engine.scan_codes.purge_scan_logs_for_document",
		) as purge_logs:
			purge_scan_registry_on_trash(pr)
		purge_logs.assert_called_once()
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

	def test_reactivate_scan_code_noops_on_blank_inputs(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", name, "status", "Used", update_modified=False)
		reactivate_scan_code("", "ASN", self._asn_name)
		self.assertEqual(frappe.db.get_value("Scan Code", name, "status"), "Used")

	def test_reactivate_upstream_from_success_scan_log(self):
		code = get_or_create_scan_code("create_purchase_receipt", "ASN", self._asn_name)
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		pr_name = "PR-SCAN-LOG-" + frappe.generate_hash(length=6)
		frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": self._asn_name,
				"result_doctype": "Purchase Receipt",
				"result_name": pr_name,
				"result": "Success",
			}
		).insert(ignore_permissions=True, ignore_links=True)
		reactivate_upstream_scan_codes_for_trashed_document(
			frappe._dict(doctype="Purchase Receipt", name=pr_name, docstatus=0)
		)
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

	def test_reactivate_upstream_reactivates_asn_gate_pass_and_scr_codes_on_pr(self):
		asn_codes = {
			"create_purchase_receipt": get_or_create_scan_code(
				"create_purchase_receipt", "ASN", self._asn_name
			),
			"create_gate_pass_from_asn": get_or_create_scan_code(
				"create_gate_pass_from_asn", "ASN", self._asn_name
			),
		}
		gp_name = "GP-REACT-" + frappe.generate_hash(length=4)
		scr_name = "SCR-REACT-" + frappe.generate_hash(length=4)
		gp_code = self._make_scan_code_direct(
			action_key="create_receipt_from_gate_pass",
			source_doctype="Gate Pass",
			source_name=gp_name,
		)
		scr_code = self._make_scan_code_direct(
			action_key="create_purchase_receipt_from_subcontracting_receipt",
			source_doctype="Subcontracting Receipt",
			source_name=scr_name,
		)
		for code_name in (*asn_codes.values(), gp_code, scr_code):
			frappe.db.set_value("Scan Code", code_name, "status", "Used", update_modified=False)

		reactivate_upstream_scan_codes_for_trashed_document(
			frappe._dict(
				doctype="Purchase Receipt",
				name="PR-LINKS",
				docstatus=0,
				asn=self._asn_name,
				custom_gate_pass_reference=gp_name,
				subcontracting_receipt=scr_name,
			)
		)
		for code_name in (*asn_codes.values(), gp_code, scr_code):
			self.assertEqual(frappe.db.get_value("Scan Code", code_name, "status"), "Active")

	def test_reactivate_upstream_on_subcontracting_receipt_and_gate_pass(self):
		for action_key in ("create_purchase_receipt", "create_gate_pass_from_asn"):
			code = get_or_create_scan_code(action_key, "ASN", self._asn_name)
			frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)

		for doctype in ("Subcontracting Receipt", "Gate Pass"):
			reactivate_upstream_scan_codes_for_trashed_document(
				frappe._dict(doctype=doctype, name="DOC-1", docstatus=0, asn=self._asn_name)
			)

		for action_key in ("create_purchase_receipt", "create_gate_pass_from_asn"):
			code = get_or_create_scan_code(action_key, "ASN", self._asn_name)
			self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

	def test_reactivate_upstream_skips_submitted_documents(self):
		with patch("asn_module.qr_engine.scan_codes.reactivate_scan_code") as reactivate:
			reactivate_upstream_scan_codes_for_trashed_document(
				frappe._dict(doctype="Purchase Receipt", name="PR-SUB", docstatus=1, asn=self._asn_name)
			)
		reactivate.assert_not_called()


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

	def test_collision_retries_until_unique_code_is_available(self):
		doc = MagicMock()
		doc.name = "BBBBBBBBBBBBBBBB"
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = None
		fake_frappe.db.exists.side_effect = [True, False]
		fake_frappe.get_doc.return_value = doc

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch(
				"asn_module.qr_engine.scan_codes._random_scan_code_value",
				side_effect=["AAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBB"],
			),
		):
			result = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-003")

		self.assertEqual(result, "BBBBBBBBBBBBBBBB")
		self.assertEqual(fake_frappe.db.exists.call_count, 2)
		fake_frappe.get_doc.assert_called_once()

	def test_unique_code_allocation_failure_throws(self):
		fake_frappe = MagicMock()
		fake_frappe.ValidationError = Exception
		fake_frappe.db.get_value.return_value = None
		fake_frappe.db.exists.return_value = True
		fake_frappe.throw.side_effect = RuntimeError("Could not allocate")

		with (
			patch("asn_module.qr_engine.scan_codes.frappe", fake_frappe),
			patch(
				"asn_module.qr_engine.scan_codes._random_scan_code_value",
				return_value="AAAAAAAAAAAAAAAA",
			),
			self.assertRaises(RuntimeError),
		):
			get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-004")

		fake_frappe.throw.assert_called_once()
		fake_frappe.get_doc.assert_not_called()
