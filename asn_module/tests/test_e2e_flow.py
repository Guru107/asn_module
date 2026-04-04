import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
	real_asn_attachment_context,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.dispatch_flow import run_asn_pr_pi_via_dispatch
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
from asn_module.utils.test_setup import before_tests


class TestEndToEndFlow(FrappeTestCase):
	"""ASN → Purchase Receipt → Purchase Invoice using scan codes and dispatch."""

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

	def test_full_asn_to_purchase_invoice_flow_via_dispatch(self):
		out = run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"E2E-{frappe.generate_hash(length=8)}",
			qty=10,
		)
		asn = out.asn
		pr = out.pr
		pi = out.pi
		purchase_order = out.purchase_order

		self.assertTrue(asn.qr_code)
		self.assertEqual(pr.docstatus, 1)
		self.assertEqual(pr.supplier, asn.supplier)
		self.assertEqual(pr.asn, asn.name)
		self.assertEqual(len(pr.items), 1)
		self.assertEqual(pr.items[0].qty, 10)
		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].received_qty, 10)
		self.assertEqual(asn.items[0].discrepancy_qty, 0)

		self.assertEqual(pi.docstatus, 0)
		self.assertEqual(pi.supplier, pr.supplier)
		self.assertEqual(pi.bill_no, asn.supplier_invoice_no)
		self.assertEqual(pi.asn, asn.name)
		self.assertEqual(purchase_order.items[0].warehouse, pr.items[0].warehouse)

	def test_discrepancy_when_purchase_receipt_qty_less_than_asn_qty(self):
		with integration_user_context():
			purchase_order = create_purchase_order(qty=10)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"DISC-{frappe.generate_hash(length=8)}",
				qty=10,
			)
			asn.insert(ignore_permissions=True)
			with real_asn_attachment_context():
				asn.submit()

			pr_code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
			pr_result = dispatch(code=pr_code, device_info="E2E-Integration")
			self.assertTrue(pr_result["success"])
			pr = frappe.get_doc("Purchase Receipt", pr_result["name"])
			pr.items[0].qty = 8
			pr.items[0].received_qty = 8
			warehouse = purchase_order.items[0].warehouse
			for row in pr.items:
				row.warehouse = warehouse
			pr.save(ignore_permissions=True)
			pr.submit()

			asn.reload()
			self.assertEqual(asn.status, "Partially Received")
			self.assertEqual(asn.items[0].received_qty, 8)
			self.assertEqual(asn.items[0].discrepancy_qty, 2)
