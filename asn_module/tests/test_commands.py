from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import (
	verify_barcode_process_flow,
	verify_qr_action_registry,
	verify_scan_code_registry,
)
from asn_module.qr_engine.scan_codes import _random_scan_code_value


class TestVerifyScanCodeRegistry(FrappeTestCase):
	def _make_orphan_scan_code(self):
		doc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": _random_scan_code_value(),
				"action_key": "STEP-TEST",
				"source_doctype": "ASN",
				"source_name": "NONEXISTENT-DOC-XYZ",
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
		return doc.name

	def test_all_valid_returns_ok(self):
		result = verify_scan_code_registry()
		self.assertIn("ok", result)

	def test_orphan_scan_code_returns_not_ok(self):
		orphan_name = self._make_orphan_scan_code()
		try:
			result = verify_scan_code_registry()
			self.assertFalse(result["ok"])
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


class TestBarcodeProcessFlowCommands(FrappeTestCase):
	def test_verify_barcode_process_flow_reports_shape(self):
		result = verify_barcode_process_flow()
		self.assertIn("ok", result)
		self.assertIn("active_flows", result)
		self.assertIn("active_steps", result)

	def test_verify_barcode_process_flow_reports_missing_doctype(self):
		with (
			patch("asn_module.commands.frappe.db.exists", return_value=False),
			patch("asn_module.commands.frappe.msgprint") as msgprint,
		):
			result = verify_barcode_process_flow()

		self.assertFalse(result["ok"])
		self.assertEqual(result["active_flows"], 0)
		self.assertEqual(result["active_steps"], 0)
		msgprint.assert_called_once()

	def test_verify_barcode_process_flow_requires_permission(self):
		with (
			patch("asn_module.commands.frappe.db.exists", return_value=True),
			patch("asn_module.commands.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			verify_barcode_process_flow()

	def test_verify_barcode_process_flow_handles_no_active_flows(self):
		with (
			patch("asn_module.commands.frappe.db.exists", return_value=True),
			patch("asn_module.commands.frappe.has_permission", return_value=True),
			patch("asn_module.commands.frappe.get_all", return_value=[]),
			patch("asn_module.commands.frappe.msgprint") as msgprint,
		):
			result = verify_barcode_process_flow()

		self.assertFalse(result["ok"])
		self.assertEqual(result["active_flows"], 0)
		self.assertEqual(result["active_steps"], 0)
		msgprint.assert_called_once()

	def test_verify_scan_code_registry_all_valid_branch(self):
		rows = [
			SimpleNamespace(
				name="SC-1",
				scan_code="CODE-ONE",
				source_doctype="ASN",
				source_name="ASN-1",
			)
		]
		with (
			patch("asn_module.commands.frappe.has_permission", return_value=True),
			patch("asn_module.commands.frappe.get_all", return_value=rows),
			patch("asn_module.commands.frappe.get_doc", return_value=SimpleNamespace(name="SC-1")),
			patch("asn_module.commands.verify_registry_row_points_to_existing_source", return_value=True),
			patch("asn_module.commands.frappe.msgprint") as msgprint,
		):
			result = verify_scan_code_registry()

		self.assertTrue(result["ok"])
		self.assertEqual(result["orphan_count"], 0)
		msgprint.assert_called_once()

	def test_verify_qr_action_registry_is_deprecated(self):
		result = verify_qr_action_registry()
		self.assertFalse(result["ok"])
		self.assertTrue(result["deprecated"])
