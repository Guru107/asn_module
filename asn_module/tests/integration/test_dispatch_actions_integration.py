"""Per-registry-key ``dispatch(code=…)`` coverage (real handlers, minimal mocks)."""

import frappe

from asn_module.handlers.tests.test_subcontracting import (
	TestSubcontractingHandlers,
	patch_subcontracting_incoming_rate,
)
from asn_module.qr_engine.dispatch import ActionNotFoundError, dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.tests.compat import IntegrationTestCase
from asn_module.tests.integration.dispatch_flow import (
	run_asn_pr_pi_via_dispatch,
	run_asn_pr_submitted_via_dispatch,
)
from asn_module.tests.integration.fixtures import (
	ensure_integration_user,
	integration_user_context,
	pin_gate_pass_mode_for_tests,
	run_failure_logs_inline_for_tests,
)
from asn_module.utils.test_setup import before_tests


class TestDispatchActionsIntegration(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		ensure_integration_user()
		pin_gate_pass_mode_for_tests(cls)
		run_failure_logs_inline_for_tests(cls)

	def test_create_purchase_receipt_and_purchase_invoice_via_dispatch(self):
		"""Covered in depth by ``test_e2e_flow``; smoke that shared flow still succeeds."""
		out = run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"DISP-PI-{frappe.generate_hash(length=8)}",
			qty=2,
		)
		self.assertTrue(out.pi.name)

	def test_confirm_putaway_is_refused_as_unknown(self):
		out = run_asn_pr_submitted_via_dispatch(
			supplier_invoice_no=f"PUT-{frappe.generate_hash(length=8)}",
			qty=2,
		)
		with integration_user_context():
			code = get_or_create_scan_code("confirm_putaway", "Purchase Receipt", out.pr.name)
			with self.assertRaises(ActionNotFoundError):
				dispatch(code=code, device_info="integration-putaway")

	def test_subcontracting_dispatches_via_scan_code(self):
		helper = TestSubcontractingHandlers()
		sco = helper._make_integration_subcontracting_order()
		with integration_user_context():
			code_dispatch = get_or_create_scan_code(
				"create_subcontracting_dispatch", "Subcontracting Order", sco.name
			)
			r1 = dispatch(code=code_dispatch, device_info="integration-sco-dispatch")
		self.assertTrue(r1.get("success"))
		self.assertEqual(r1.get("doctype"), "Stock Entry")
		ste = frappe.get_doc("Stock Entry", r1["name"])
		self.assertEqual(ste.stock_entry_type, "Send to Subcontractor")
		self.assertEqual(ste.docstatus, 0)

		with integration_user_context():
			with patch_subcontracting_incoming_rate(5):
				code_receipt = get_or_create_scan_code(
					"create_subcontracting_receipt", "Subcontracting Order", sco.name
				)
				r2 = dispatch(code=code_receipt, device_info="integration-sco-receipt")
		self.assertTrue(r2.get("success"))
		self.assertEqual(r2.get("doctype"), "Subcontracting Receipt")
		scr = frappe.get_doc("Subcontracting Receipt", r2["name"])
		self.assertEqual(scr.docstatus, 0)
		self.assertTrue(scr.items)
