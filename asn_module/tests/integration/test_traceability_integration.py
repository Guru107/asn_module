"""ASN Transition Log alignment with summary and report (integration)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.asn import get_item_transition_summary
from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.dispatch_flow import run_asn_pr_pi_via_dispatch
from asn_module.tests.integration.fixtures import ensure_integration_user
from asn_module.utils.test_setup import before_tests


class TestTraceabilityIntegration(FrappeTestCase):
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

	def test_transition_log_summary_and_report_align_after_asn_pr_pi(self):
		inv = f"TRACE-{frappe.generate_hash(length=8)}"
		out = run_asn_pr_pi_via_dispatch(supplier_invoice_no=inv, qty=10)
		asn = out.asn

		log_count = frappe.db.count("ASN Transition Log", {"asn": asn.name})
		self.assertGreaterEqual(log_count, 3)

		states = frappe.get_all(
			"ASN Transition Log",
			filters={"asn": asn.name},
			pluck="state",
		)
		self.assertIn("ASN_GENERATED", states)
		self.assertIn("PR_CREATED_DRAFT", states)
		self.assertIn("PR_SUBMITTED", states)

		summary = get_item_transition_summary(asn.name)
		self.assertGreaterEqual(len(summary), 1)

		columns, rows = execute({"asn": asn.name, "limit_page_length": 100})
		self.assertEqual(len(columns), 10)
		self.assertEqual(len(rows), log_count)
