import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	before_tests,
	create_purchase_order_with_fiscal_dates,
)
from asn_module.handlers.putaway import confirm_putaway


class TestConfirmPutaway(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_draft_purchase_receipt(self):
		purchase_order = create_purchase_order_with_fiscal_dates()
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": purchase_order.supplier,
				"company": purchase_order.company,
				"items": [
					{
						"item_code": purchase_order.items[0].item_code,
						"qty": 1,
						"rate": purchase_order.items[0].rate,
						"purchase_order": purchase_order.name,
						"purchase_order_item": purchase_order.items[0].name,
						"warehouse": purchase_order.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		return pr

	def test_creates_scan_log_for_putaway(self):
		pr = self._make_draft_purchase_receipt()

		result = confirm_putaway(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={
				"action": "confirm_putaway",
				"source_doctype": "Purchase Receipt",
				"source_name": pr.name,
				"device_info": "Ignored-For-Putaway-Spec",
			},
		)

		self.assertEqual(result["doctype"], "Scan Log")
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.action, "confirm_putaway")
		self.assertEqual(log.result, "Success")
		self.assertEqual(log.device_info, "Desktop")

	def test_putaway_rejects_missing_source_document(self):
		missing_name = f"PR-MISSING-{frappe.generate_hash(length=10)}"
		with self.assertRaises(frappe.ValidationError):
			confirm_putaway("Purchase Receipt", missing_name, payload={})
