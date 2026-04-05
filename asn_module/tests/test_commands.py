from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_qr_action_registry, verify_scan_code_registry
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions


class TestVerifyScanCodeRegistry(FrappeTestCase):
	def test_all_valid_returns_ok(self):
		result = verify_scan_code_registry()
		self.assertTrue(result["ok"])
		self.assertEqual(result["orphan_count"], 0)

	def test_orphan_scan_code_returns_not_ok(self):
		name = get_or_create_scan_code(
			"create_purchase_receipt", "ASN", f"ORPHAN-CMD-{frappe.generate_hash(length=6)}"
		)
		frappe.db.set_value(
			"Scan Code", name, "source_name", "NONEXISTENT-DOC-XYZ", update_modified=False
		)
		result = verify_scan_code_registry()
		self.assertFalse(result["ok"])
		self.assertGreater(result["orphan_count"], 0)

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
		for row in list(reg.actions):
			if row.action_key == "confirm_putaway":
				reg.remove(row)
				break
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertIn("confirm_putaway", result["missing"])
		finally:
			register_actions()

	def test_mismatched_handler_detected(self):
		reg = frappe.get_doc("QR Action Registry")
		for row in reg.actions:
			if row.action_key == "confirm_putaway":
				row.handler_method = "wrong.handler.path"
				break
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertTrue(
				any(m["action_key"] == "confirm_putaway" for m in result["mismatched"])
			)
		finally:
			register_actions()
