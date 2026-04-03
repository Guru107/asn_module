import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	before_tests,
	create_purchase_order,
	make_test_asn,
)
from asn_module.handlers.purchase_receipt import create_from_asn


class TestCreatePurchaseReceipt(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_submitted_asn(self):
		purchase_order = create_purchase_order(
			transaction_date="2026-03-30",
			schedule_date="2026-03-31",
			item_schedule_date="2026-03-31",
		)
		asn = make_test_asn(purchase_order=purchase_order)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()
		return asn

	def test_creates_draft_purchase_receipt_from_asn(self):
		asn = self._make_submitted_asn()

		result = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)

		self.assertEqual(result["doctype"], "Purchase Receipt")
		pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(pr.docstatus, 0)
		self.assertEqual(pr.supplier, asn.supplier)
		self.assertEqual(pr.asn, asn.name)
		self.assertEqual(len(pr.items), 1)
		self.assertEqual(pr.items[0].item_code, asn.items[0].item_code)
		self.assertEqual(pr.items[0].qty, asn.items[0].qty)

	def test_duplicate_scan_returns_existing_draft_purchase_receipt(self):
		asn = self._make_submitted_asn()

		first = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		second = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)

		self.assertEqual(first["name"], second["name"])
		self.assertEqual(
			frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": 0}),
			1,
		)

	def test_rejects_asn_with_status_received(self):
		asn = self._make_submitted_asn()
		frappe.db.set_value("ASN", asn.name, "status", "Received", update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			create_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_rejects_asn_with_status_closed(self):
		asn = self._make_submitted_asn()
		frappe.db.set_value("ASN", asn.name, "status", "Closed", update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			create_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)
