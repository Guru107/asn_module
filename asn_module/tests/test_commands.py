from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_scan_code_registry
from asn_module.qr_engine.scan_codes import _random_scan_code_value


class TestVerifyScanCodeRegistry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for row in frappe.get_all("Scan Code", filters={"source_doctype": "Bogus DocType"}):
			frappe.delete_doc("Scan Code", row["name"], force=True, ignore_permissions=True)
		# Defensive cleanup for orphan rows created by failure-path integration tests.
		for row in frappe.get_all(
			"Scan Code",
			filters={
				"source_doctype": "ASN",
				"source_name": ["in", ["Fake-ASN-For-Test", "NONEXISTENT-DOC-XYZ"]],
			},
			pluck="name",
		):
			frappe.delete_doc("Scan Code", row, force=True, ignore_permissions=True)
		# On persistent dev sites, dispatch's failure-path commit can leave scan codes
		# behind when a later suite raw-deletes their source; sweep any committed
		# orphans so the happy-path assertion only sees this run's state.
		for row in verify_scan_code_registry().get("orphans", []):
			frappe.delete_doc("Scan Code", row["name"], force=True, ignore_permissions=True)

	def _make_orphan_scan_code(self):
		doc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": _random_scan_code_value(),
				"action_key": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": "ORPHAN-CMD-" + frappe.generate_hash(length=6),
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
		frappe.db.set_value(
			"Scan Code", doc.name, "source_name", "NONEXISTENT-DOC-XYZ", update_modified=False
		)
		return doc.name

	def test_all_valid_returns_ok(self):
		result = verify_scan_code_registry()
		self.assertTrue(result["ok"])
		self.assertEqual(result["orphan_count"], 0)

	def test_orphan_scan_code_returns_not_ok(self):
		orphan_name = self._make_orphan_scan_code()
		try:
			result = verify_scan_code_registry()
			self.assertFalse(result["ok"])
			self.assertGreater(result["orphan_count"], 0)
			orphan_names = [o["name"] for o in result["orphans"]]
			self.assertIn(orphan_name, orphan_names)
		finally:
			frappe.delete_doc("Scan Code", orphan_name, force=True, ignore_permissions=True)

	def test_permission_check(self):
		with (
			patch("asn_module.commands.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			verify_scan_code_registry()
