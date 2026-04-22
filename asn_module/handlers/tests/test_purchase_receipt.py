import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	before_tests,
	create_purchase_order_with_fiscal_dates,
	make_test_asn,
	make_test_asn_with_two_items,
)
from asn_module.handlers.purchase_receipt import create_from_asn, on_purchase_receipt_submit
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


class TestCreatePurchaseReceipt(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_submitted_asn(self):
		dates = get_fiscal_year_test_dates()
		purchase_order = create_purchase_order_with_fiscal_dates(
			transaction_date=dates["transaction_date"],
			schedule_date=dates["schedule_date"],
			item_schedule_date=dates["item_schedule_date"],
		)
		asn = make_test_asn(purchase_order=purchase_order)
		asn.supplier_invoice_no = f"INV-PR-PREFILL-{frappe.generate_hash(length=6)}"
		asn.transporter_name = "MAS Logistics"
		asn.lr_no = "LR-0001"
		asn.lr_date = dates["lr_date"]
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
		self.assertEqual(pr.supplier_delivery_note, asn.supplier_invoice_no)
		self.assertEqual(pr.transporter_name, asn.transporter_name)
		self.assertEqual(pr.lr_no, asn.lr_no)
		self.assertEqual(str(pr.lr_date), str(asn.lr_date))
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

	def test_rejects_draft_asn(self):
		purchase_order = create_purchase_order_with_fiscal_dates()
		asn = make_test_asn(purchase_order=purchase_order)
		asn.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			create_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_submit_updates_asn_without_auto_qr_generation(self):
		purchase_order = create_purchase_order_with_fiscal_dates(qty=10)
		asn = make_test_asn_with_two_items(purchase_order=purchase_order, qty=5)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		result = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		pr = frappe.get_doc("Purchase Receipt", result["name"])

		on_purchase_receipt_submit(pr, "on_submit")
		asn.reload()

		self.assertEqual(asn.status, "Received")
		self.assertEqual([row.received_qty for row in asn.items], [5, 5])
		self.assertEqual([row.discrepancy_qty for row in asn.items], [0, 0])
