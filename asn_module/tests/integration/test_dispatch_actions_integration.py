"""Per-registry-key ``dispatch(code=…)`` coverage (real handlers, minimal mocks)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.handlers.tests.test_purchase_return import TestCreatePurchaseReturn
from asn_module.handlers.tests.test_stock_transfer import TestCreateStockTransfer
from asn_module.handlers.tests.test_subcontracting import (
	TestSubcontractingHandlers,
	patch_subcontracting_incoming_rate,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.tests.integration.dispatch_flow import (
	run_asn_pr_pi_via_dispatch,
	run_asn_pr_submitted_via_dispatch,
)
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
from asn_module.utils.test_setup import before_tests


class TestDispatchActionsIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		ensure_integration_user()

	def test_create_purchase_receipt_and_purchase_invoice_via_dispatch(self):
		"""Covered in depth by ``test_e2e_flow``; smoke that shared flow still succeeds."""
		out = run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"DISP-PI-{frappe.generate_hash(length=8)}",
			qty=2,
		)
		self.assertTrue(out.pi.name)

	def test_confirm_putaway_via_dispatch(self):
		out = run_asn_pr_submitted_via_dispatch(
			supplier_invoice_no=f"PUT-{frappe.generate_hash(length=8)}",
			qty=2,
		)
		with integration_user_context():
			code = get_or_create_scan_code("confirm_putaway", "Purchase Receipt", out.pr.name)
			result = dispatch(code=code, device_info="integration-putaway")
		self.assertTrue(result.get("success"))
		self.assertEqual(result.get("doctype"), "Scan Log")

		states = frappe.get_all(
			"ASN Transition Log",
			filters={"asn": out.asn.name, "state": "PUTAWAY_CONFIRMED"},
			pluck="name",
		)
		self.assertEqual(len(states), 1)

	def test_create_stock_transfer_via_dispatch(self):
		fixture = TestCreateStockTransfer()
		_pr, qi = fixture._make_purchase_receipt_with_qi("Accepted")
		with integration_user_context():
			code = get_or_create_scan_code("create_stock_transfer", "Quality Inspection", qi.name)
			result = dispatch(code=code, device_info="integration-st")
		self.assertTrue(result.get("success"))
		self.assertEqual(result.get("doctype"), "Stock Entry")
		se = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(se.docstatus, 0)
		self.assertEqual(se.stock_entry_type, "Material Transfer")

	def test_create_purchase_return_via_dispatch(self):
		fixture = TestCreatePurchaseReturn()
		pr, qi = fixture._make_rejected_purchase_receipt_with_qi()
		with integration_user_context():
			code = get_or_create_scan_code("create_purchase_return", "Quality Inspection", qi.name)
			result = dispatch(code=code, device_info="integration-prret")
		self.assertTrue(result.get("success"))
		self.assertEqual(result.get("doctype"), "Purchase Receipt")
		ret = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(ret.docstatus, 0)
		self.assertEqual(ret.is_return, 1)
		self.assertEqual(ret.return_against, pr.name)

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
