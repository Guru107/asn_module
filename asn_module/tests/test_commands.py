from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_scan_code_registry
from asn_module.qr_engine.scan_codes import _random_scan_code_value
from asn_module.setup_actions import ACTIONS


class TestVerifyScanCodeRegistry(FrappeTestCase):
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

	def test_orphans_are_reported_in_constant_round_trips(self):
		orphan_name = self._make_orphan_scan_code()
		real_sql = frappe.db.sql
		sql_calls = []

		def counting_sql(*args, **kwargs):
			sql_calls.append(args[0] if args else None)
			return real_sql(*args, **kwargs)

		try:
			with (
				patch("asn_module.commands.frappe.has_permission", return_value=True),
				patch("asn_module.commands.frappe.db.sql", side_effect=counting_sql),
			):
				result = verify_scan_code_registry()

			# Constant round trips, independent of registry size: one DocType
			# existence filter (registry doctypes may be uninstalled, e.g. Gate
			# Pass) plus one NOT EXISTS anti-join. The old implementation ran
			# two queries per Scan Code row.
			self.assertEqual(len(sql_calls), 2)
			self.assertIn("tabDocType", sql_calls[0])
			self.assertIn("NOT (", sql_calls[1])
			self.assertIn("EXISTS", sql_calls[1])
			self.assertFalse(result["ok"])
			orphan_names = [o["name"] for o in result["orphans"]]
			self.assertIn(orphan_name, orphan_names)
		finally:
			frappe.delete_doc("Scan Code", orphan_name, force=True, ignore_permissions=True)

	def test_uninstalled_registry_doctype_is_skipped(self):
		"""A registry doctype whose app is absent must not crash the anti-join."""
		doc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": _random_scan_code_value(),
				"action_key": "create_purchase_receipt",
				"source_doctype": "No Such Installed DocType",
				"source_name": "whatever",
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
		fake_actions = dict(ACTIONS)
		fake_actions["fake_missing_action"] = {
			"handler": "no.such.handler",
			"source_doctype": "No Such Installed DocType",
			"roles": ["System Manager"],
		}
		try:
			with (
				patch("asn_module.commands.ACTIONS", fake_actions),
				patch("asn_module.commands.frappe.has_permission", return_value=True),
			):
				result = verify_scan_code_registry()

			self.assertFalse(result["ok"])
			self.assertIn(doc.name, [o["name"] for o in result["orphans"]])
		finally:
			frappe.delete_doc("Scan Code", doc.name, force=True, ignore_permissions=True)

	def test_permission_check(self):
		with (
			patch("asn_module.commands.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			verify_scan_code_registry()
