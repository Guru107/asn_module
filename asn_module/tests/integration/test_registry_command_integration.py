"""``verify_scan_code_registry`` happy and orphan paths."""

import secrets

import frappe

from asn_module.commands import verify_scan_code_registry
from asn_module.qr_engine.scan_codes import SCAN_CODE_ALPHABET, SCAN_CODE_LENGTH
from asn_module.tests.compat import IntegrationTestCase
from asn_module.tests.integration.dispatch_flow import run_asn_pr_pi_via_dispatch
from asn_module.tests.integration.fixtures import (
	ensure_integration_user,
	integration_user_context,
	pin_gate_pass_mode_for_tests,
)
from asn_module.utils.test_setup import before_tests


class TestRegistryCommandIntegration(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		ensure_integration_user()
		pin_gate_pass_mode_for_tests(cls)

	def test_verify_registry_ok_after_dispatch_flow(self):
		flow = run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"REG-OK-{frappe.generate_hash(length=8)}",
			qty=3,
		)
		flow_codes = frappe.get_all(
			"Scan Code",
			filters={"source_name": ("in", [flow.asn.name, flow.pr.name, flow.pi.name])},
			pluck="name",
		)
		self.assertIn(flow.pr_code, flow_codes)
		self.assertIn(flow.pi_code, flow_codes)
		with integration_user_context():
			result = verify_scan_code_registry()
		# Asserts on this flow's codes only: the dev site may hold unrelated orphans.
		self.assertFalse(set(flow_codes) & {o["name"] for o in result["orphans"]})

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
