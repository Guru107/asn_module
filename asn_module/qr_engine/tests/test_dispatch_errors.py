"""Integration tests for error branches in ``asn_module/qr_engine/dispatch.py``."""

import secrets
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.dispatch import ScanCodeNotFoundError, dispatch
from asn_module.qr_engine.scan_codes import SCAN_CODE_ALPHABET, SCAN_CODE_LENGTH
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
from asn_module.utils.test_setup import before_tests


class TestDispatchErrorsIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		register_actions()
		ensure_integration_user()

	def _create_scan_code(self, action_key, source_doctype, source_name):
		code_val = "".join(secrets.choice(SCAN_CODE_ALPHABET) for _ in range(SCAN_CODE_LENGTH))
		sc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": code_val,
				"action_key": action_key,
				"source_doctype": source_doctype,
				"source_name": source_name,
				"status": "Active",
			}
		)
		sc.insert(ignore_permissions=True, ignore_links=True)
		return code_val

	def _cleanup_scan_code(self, code):
		if frappe.db.exists("Scan Code", code):
			frappe.delete_doc("Scan Code", code, force=True, ignore_permissions=True)

	def test_handler_returning_string_raises_validation_error(self):
		code = self._create_scan_code("create_purchase_receipt", "ASN", "Fake-ASN-For-Test")
		self.addCleanup(self._cleanup_scan_code, code)

		with integration_user_context():
			with patch(
				"asn_module.qr_engine.dispatch._call_handler",
				return_value="not a dict",
			):
				with self.assertRaises(frappe.ValidationError) as cm:
					dispatch(code=code, device_info="test")
				self.assertIn("Invalid handler result", str(cm.exception))

	def test_handler_returning_error_dict_raises_validation_error(self):
		code = self._create_scan_code("create_purchase_receipt", "ASN", "Fake-ASN-For-Test")
		self.addCleanup(self._cleanup_scan_code, code)

		def error_handler(handler_method, source_doctype, source_name, payload):
			return {"success": False, "message": "intentional handler error"}

		with integration_user_context():
			with patch(
				"asn_module.qr_engine.dispatch._call_handler",
				side_effect=error_handler,
			):
				with self.assertRaises(frappe.ValidationError) as cm:
					dispatch(code=code, device_info="test")
				self.assertIn("missing", str(cm.exception).lower())

	def test_dispatch_missing_scan_code_raises(self):
		with integration_user_context():
			with self.assertRaises(ScanCodeNotFoundError) as cm:
				dispatch(code=None, device_info="test")
			self.assertIn("Missing scan code", str(cm.exception))

	def test_dispatch_unknown_scan_code_raises(self):
		with integration_user_context():
			with self.assertRaises(ScanCodeNotFoundError) as cm:
				dispatch(code="ASNLONGCODENOTEXIST1234", device_info="test")
			self.assertIn("Unknown or invalid scan code", str(cm.exception))
