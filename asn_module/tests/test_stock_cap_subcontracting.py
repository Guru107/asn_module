import frappe
from frappe.utils import today

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
from asn_module.handlers.subcontracting import (
	create_receipt_from_subcontracting_order,
	on_subcontracting_receipt_before_submit,
)
from asn_module.handlers.tests.test_subcontracting import (
	TestSubcontractingHandlers,
	patch_subcontracting_incoming_rate,
)
from asn_module.stock_cap.api import breaches_for_asn_rows
from asn_module.stock_cap.collect import collect_lines_from_asn_rows
from asn_module.templates.pages.asn_new_services import create_job_asn_for_supplier
from asn_module.tests.compat import IntegrationTestCase
from asn_module.utils.test_setup import (
	before_tests,
	build_purchase_order_with_mandatory_fields,
	delete_asns_with_items,
	disable_hsn_validation,
	resolve_test_company,
)

BRANCH = "_Test Job Stock Cap Branch"
FG_ITEM = "_Test Subcontract FG Item"


class TestStockCapSubcontracting(IntegrationTestCase):
	"""Job ASNs and Subcontracting Receipts are capped, and a Job ASN counts as in transit."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()
		if not frappe.db.exists("Branch", BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)

	def setUp(self):
		# FrappeTestCase rolls back only at class teardown; clear what an earlier test left.
		self.order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		self.finished_good = self.order.items[0]
		self.warehouse = self.finished_good.warehouse
		delete_asns_with_items([FG_ITEM])
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": BRANCH,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)
		bin_name = frappe.db.get_value("Bin", {"item_code": FG_ITEM, "warehouse": self.warehouse}, "name")
		if bin_name:
			frappe.db.set_value("Bin", bin_name, "actual_qty", 0, update_modified=False)

	def _set_cap(self, max_qty: float) -> None:
		frappe.db.delete("ASN Item Branch Cap", {"item": FG_ITEM})
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": FG_ITEM, "max_qty": max_qty}
		).insert(ignore_permissions=True)

	def _job_asn(self, qty: float):
		return create_job_asn_for_supplier(
			supplier=self.order.supplier,
			subcontracting_order=self.order.name,
			header={
				"supplier_invoice_no": f"JOB-CAP-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": qty * self.finished_good.rate,
			},
			lines=[{"subcontracting_order_item": self.finished_good.name, "qty": qty}],
		)

	def _draft_receipt(self):
		with patch_subcontracting_incoming_rate(5):
			result = create_receipt_from_subcontracting_order("Subcontracting Order", self.order.name, {})
		return frappe.get_doc("Subcontracting Receipt", result["name"])

	def test_job_asn_over_the_cap_is_blocked_on_submit(self):
		self._set_cap(1)
		asn = self._job_asn(2)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.submit()

		self.assertIn(FG_ITEM, str(raised.exception))

	def test_job_asn_exactly_at_the_cap_submits(self):
		self._set_cap(2)
		asn = self._job_asn(2)

		asn.submit()

		self.assertEqual(asn.docstatus, 1)

	def test_job_asn_qty_uses_the_subcontracting_order_item_conversion_factor(self):
		frappe.db.set_value(
			"Subcontracting Order Item",
			self.finished_good.name,
			"conversion_factor",
			2.5,
			update_modified=False,
		)
		rows = [
			{
				"idx": 1,
				"subcontracting_order_item": self.finished_good.name,
				"item_code": FG_ITEM,
				"qty": 2.0,
			}
		]

		lines = collect_lines_from_asn_rows(rows)

		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].stock_qty, 5.0)
		self.assertEqual(lines[0].warehouse, self.warehouse)

	def test_material_asn_sees_the_job_asns_in_transit_qty(self):
		self._set_cap(3)
		self._job_asn(2).submit()
		purchase_order = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Job Stock Cap Tax",
			do_not_submit=True,
			company=resolve_test_company(),
			item_code=FG_ITEM,
			warehouse=self.warehouse,
			qty=10,
		)
		po_item = purchase_order.items[0]
		rows = [
			{
				"idx": 1,
				"purchase_order": purchase_order.name,
				"purchase_order_item": po_item.name,
				"item_code": FG_ITEM,
				"qty": 2.0,
			}
		]

		breaches, _accepted = breaches_for_asn_rows(rows)

		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].in_transit, 2.0)

	def test_subcontracting_receipt_over_the_cap_is_blocked(self):
		self._set_cap(1)
		receipt = self._draft_receipt()
		self.assertEqual(receipt.items[0].qty, 2)

		with self.assertRaises(frappe.ValidationError) as raised:
			on_subcontracting_receipt_before_submit(receipt)

		self.assertIn(FG_ITEM, str(raised.exception))

	def test_subcontracting_receipt_return_is_not_blocked(self):
		self._set_cap(1)
		receipt = self._draft_receipt()
		receipt.is_return = 1

		on_subcontracting_receipt_before_submit(receipt)

	def test_receipt_linked_to_its_job_asn_does_not_count_that_shipment_twice(self):
		self._set_cap(2)
		asn = self._job_asn(2)
		asn.submit()
		receipt = self._draft_receipt()

		receipt.asn = None
		with self.assertRaises(frappe.ValidationError):
			on_subcontracting_receipt_before_submit(receipt)

		receipt.asn = asn.name
		on_subcontracting_receipt_before_submit(receipt)
