"""``verify_scan_code_registry`` happy and orphan paths."""

import secrets

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_scan_code_registry
from asn_module.qr_engine.scan_codes import SCAN_CODE_ALPHABET, SCAN_CODE_LENGTH
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.dispatch_flow import run_asn_pr_pi_via_dispatch
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
from asn_module.utils.test_setup import before_tests


class TestRegistryCommandIntegration(FrappeTestCase):
	@classmethod
	def _snapshot_registry_actions(cls) -> list[dict]:
		reg = frappe.get_doc("QR Action Registry")
		return [
			{
				"action_key": row.action_key,
				"handler_method": row.handler_method,
				"source_doctype": row.source_doctype,
				"allowed_roles": row.allowed_roles,
			}
			for row in (reg.actions or [])
		]

	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		cls._registry_snapshot = cls._snapshot_registry_actions()
		register_actions()
		ensure_integration_user()

	@classmethod
	def tearDownClass(cls):
		reg = frappe.get_doc("QR Action Registry")
		reg.set("actions", [])
		for row in cls._registry_snapshot:
			reg.append("actions", row)
		reg.save(ignore_permissions=True)
		super().tearDownClass()

	def test_verify_registry_ok_after_dispatch_flow(self):
		# Rows from ``test_dispatch_rejects_source_doctype_mismatch`` (legacy fixed code or failed cleanups).
		for name in frappe.get_all(
			"Scan Code",
			filters={"source_doctype": "Bogus DocType", "source_name": "Bogus Name"},
			pluck="name",
		):
			frappe.delete_doc("Scan Code", name, force=True, ignore_permissions=True)

		run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"REG-OK-{frappe.generate_hash(length=8)}",
			qty=3,
		)
		with integration_user_context():
			result = verify_scan_code_registry()
		self.assertTrue(result["ok"])
		self.assertEqual(result["orphan_count"], 0)

	def test_verify_registry_lists_orphan_scan_code(self):
		orphan_name = None
		try:
			code_val = "".join(secrets.choice(SCAN_CODE_ALPHABET) for _ in range(SCAN_CODE_LENGTH))
			doc = frappe.get_doc(
				{
					"doctype": "Scan Code",
					"scan_code": code_val,
					"action_key": "create_purchase_receipt",
					"source_doctype": "ASN",
					"source_name": f"NONEXISTENT-{frappe.generate_hash(length=8)}",
					"status": "Active",
				}
			)
			# Dynamic Link would reject a missing ASN; bypass so orphan rows are possible (like DB drift).
			doc.insert(ignore_permissions=True, ignore_links=True)
			orphan_name = doc.name

			with integration_user_context():
				result = verify_scan_code_registry()
			self.assertFalse(result["ok"])
			self.assertGreaterEqual(result["orphan_count"], 1)
			orphan_names = {o["name"] for o in result["orphans"]}
			self.assertIn(orphan_name, orphan_names)
		finally:
			if orphan_name and frappe.db.exists("Scan Code", orphan_name):
				frappe.delete_doc("Scan Code", orphan_name, force=True, ignore_permissions=True)
