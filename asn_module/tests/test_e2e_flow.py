import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.asn import remaining_qty_by_purchase_order_item
from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.stock_cap.fetch import fetch_cap_context
from asn_module.stock_cap.models import Line
from asn_module.tests.integration.dispatch_flow import run_asn_pr_pi_via_dispatch
from asn_module.tests.integration.fixtures import (
	ensure_integration_user,
	integration_user_context,
	pin_gate_pass_mode_for_tests,
)
from asn_module.utils.test_setup import before_tests


class TestEndToEndFlow(FrappeTestCase):
	"""ASN → Purchase Receipt → Purchase Invoice using scan codes and dispatch."""

	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		ensure_integration_user()
		pin_gate_pass_mode_for_tests(cls)

	def test_full_asn_to_purchase_invoice_flow_via_dispatch(self):
		out = run_asn_pr_pi_via_dispatch(
			supplier_invoice_no=f"E2E-{frappe.generate_hash(length=8)}",
			qty=10,
		)
		asn = out.asn
		pr = out.pr
		pi = out.pi
		purchase_order = out.purchase_order

		self.assertTrue(asn.scan_code_label)
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

	def test_short_receipt_closes_asn_and_cancel_reopens_it(self):
		with integration_user_context():
			purchase_order = create_purchase_order(qty=10)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"DISC-{frappe.generate_hash(length=8)}",
				qty=10,
			)
			asn.insert(ignore_permissions=True)
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
			self.assertEqual(asn.status, "Closed")
			self.assertEqual(asn.items[0].received_qty, 8)
			self.assertEqual(asn.items[0].discrepancy_qty, 2)

			po_item = purchase_order.items[0]
			line = _cap_line_for(po_item)
			self.assertEqual(_in_transit(line), 0.0)
			# A Closed ASN holds back none of the short qty: Remaining Qty frees it.
			self.assertEqual(
				remaining_qty_by_purchase_order_item({po_item.name: 10}),
				remaining_qty_by_purchase_order_item({po_item.name: 10}, exclude_asn_name=asn.name),
			)

			with self.assertRaises(frappe.ValidationError):
				dispatch(code=pr_code, device_info="E2E-Integration")
			self.assertEqual(
				frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": ["!=", 2]}), 1
			)

		pr.reload()
		pr.cancel()
		asn.reload()
		self.assertEqual(asn.status, "Submitted")
		self.assertEqual(asn.items[0].received_qty, 0)
		self.assertEqual(_in_transit(line), 10.0 * (po_item.conversion_factor or 1))


_E2E_BRANCH = "_Test E2E Branch"


def _cap_line_for(po_item) -> Line:
	"""Turn on the stock cap for the PO line's warehouse so its In Transit can be read."""
	if not frappe.db.exists("Branch", _E2E_BRANCH):
		frappe.get_doc({"doctype": "Branch", "branch": _E2E_BRANCH}).insert(ignore_permissions=True)
	if not frappe.db.exists("ASN Stock Cap Settings", {"branch": _E2E_BRANCH}):
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": _E2E_BRANCH,
				"enabled": 1,
				"warehouses": [{"warehouse": po_item.warehouse}],
			}
		).insert(ignore_permissions=True)
	return Line(
		branch=_E2E_BRANCH, item_code=po_item.item_code, warehouse=po_item.warehouse, stock_qty=1.0, row_idx=1
	)


def _in_transit(line: Line) -> float:
	return fetch_cap_context([line]).in_transit.get((line.branch, line.item_code), 0.0)
