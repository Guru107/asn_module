from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_qr_action_registry, verify_scan_code_registry
from asn_module.qr_engine.scan_codes import _random_scan_code_value
from asn_module.setup_actions import register_actions


class TestVerifyScanCodeRegistry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for row in frappe.get_all("Scan Code", filters={"source_doctype": "Bogus DocType"}):
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


class TestVerifyQrActionRegistry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		register_actions()

	def test_all_canonical_actions_present_returns_ok(self):
		result = verify_qr_action_registry()
		self.assertTrue(result["ok"])
		self.assertEqual(result["missing"], [])
		self.assertEqual(result["mismatched"], [])

	def test_missing_action_detected(self):
		reg = frappe.get_doc("QR Action Registry")
		saved_actions = list(reg.actions)
		reg.actions = [row for row in saved_actions if row.action_key != "confirm_putaway"]
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertIn("confirm_putaway", result["missing"])
		finally:
			reg.actions = saved_actions
			reg.save(ignore_permissions=True)

	def test_mismatched_handler_detected(self):
		reg = frappe.get_doc("QR Action Registry")
		saved_actions = list(reg.actions)
		for row in reg.actions:
			if row.action_key == "confirm_putaway":
				row.handler_method = "wrong.handler.path"
				break
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertTrue(any(m["action_key"] == "confirm_putaway" for m in result["mismatched"]))
		finally:
			reg.actions = saved_actions
			reg.save(ignore_permissions=True)
