from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	before_tests,
	create_purchase_order_with_fiscal_dates,
	make_test_asn,
	make_test_asn_with_two_items,
)
from asn_module.handlers.purchase_receipt import (
	create_from_asn,
	on_purchase_receipt_submit,
	on_purchase_receipt_trash,
)
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

	def test_create_from_asn_returns_existing_draft_without_creating_new_doc(self):
		asn = SimpleNamespace(docstatus=1, status="Submitted", name="ASN-UNIT-001")
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc", return_value=asn),
			patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", return_value="PR-DRAFT-001"),
			patch("asn_module.handlers.purchase_receipt.frappe.new_doc") as new_doc,
		):
			result = create_from_asn("ASN", "ASN-UNIT-001", payload={})

		self.assertEqual(result["name"], "PR-DRAFT-001")
		self.assertIn("/app/purchase-receipt/PR-DRAFT-001", result["url"])
		new_doc.assert_not_called()

	def test_create_from_asn_builds_purchase_receipt_and_transition_logs(self):
		asn_item = SimpleNamespace(
			idx=1,
			name="ASN-ITEM-001",
			item_code="ITEM-001",
			item_name="Item 001",
			qty=3,
			uom="Nos",
			rate=25,
			batch_no=None,
			serial_nos=None,
			purchase_order="PO-001",
			purchase_order_item="POI-001",
		)
		asn = SimpleNamespace(
			docstatus=1,
			status="Submitted",
			name="ASN-UNIT-002",
			supplier="Supp-001",
			supplier_invoice_no="INV-UNIT-002",
			transporter_name="Carrier",
			lr_no="LR-UNIT",
			lr_date="2026-04-26",
			items=[asn_item],
		)

		class _FakePurchaseReceipt(SimpleNamespace):
			def __init__(self):
				super().__init__(
					items=[
						SimpleNamespace(
							idx=1,
							item_code="ITEM-001",
							purchase_order="PO-001",
							purchase_order_item="POI-001",
							warehouse="Stores - TCPL",
							rate=25,
							conversion_factor=1,
						)
					],
					name="PR-UNIT-002",
					company="TCPL",
					currency="INR",
					conversion_rate=1,
				)

			def insert(self, **kwargs):
				self.insert_kwargs = kwargs

		pr = _FakePurchaseReceipt()
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc", return_value=asn),
			patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", return_value=None),
			patch("asn_module.handlers.purchase_receipt.make_purchase_receipt", return_value=pr) as make_pr,
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition") as emit,
		):
			result = create_from_asn("ASN", "ASN-UNIT-002", payload={})

		self.assertEqual(result["name"], "PR-UNIT-002")
		self.assertEqual(pr.supplier, "Supp-001")
		self.assertEqual(pr.company, "TCPL")
		self.assertEqual(pr.currency, "INR")
		self.assertEqual(pr.supplier_delivery_note, "INV-UNIT-002")
		self.assertEqual(pr.items[0].purchase_order_item, "POI-001")
		self.assertEqual(pr.items[0].warehouse, "Stores - TCPL")
		self.assertEqual(pr.items[0].qty, 3)
		self.assertEqual(pr.items[0].amount, 75)
		self.assertEqual(pr.asn_items, '{"1": {"asn_item_name": "ASN-ITEM-001", "original_qty": 3}}')
		self.assertEqual(pr.insert_kwargs, {"ignore_permissions": True})
		make_pr.assert_called_once_with("PO-001", args={"filtered_children": ["POI-001"]})
		emit.assert_called_once()

	def test_on_purchase_receipt_submit_returns_when_not_linked_to_asn(self):
		with patch("asn_module.handlers.purchase_receipt.frappe.get_doc") as get_doc:
			on_purchase_receipt_submit(SimpleNamespace(asn=None), "on_submit")

		get_doc.assert_not_called()

	def test_on_purchase_receipt_trash_deletes_draft_creation_transition_logs(self):
		doc = SimpleNamespace(name="PR-UNIT-004", docstatus=0, asn="ASN-UNIT-004")

		with (
			patch("asn_module.handlers.purchase_receipt.frappe.db.delete") as delete,
			patch("asn_module.handlers.purchase_receipt.frappe.db.set_value") as set_value,
		):
			on_purchase_receipt_trash(doc, "on_trash")

		self.assertEqual(delete.call_count, 2)
		delete.assert_any_call(
			"ASN Transition Log",
			{
				"ref_doctype": "Purchase Receipt",
				"ref_name": "PR-UNIT-004",
				"state": "PR_CREATED_DRAFT",
			},
		)
		delete.assert_any_call(
			"Scan Log",
			{
				"action": "create_purchase_receipt",
				"result_doctype": "Purchase Receipt",
				"result_name": "PR-UNIT-004",
				"result": "Success",
			},
		)
		set_value.assert_called_once_with(
			"Scan Code",
			{
				"action_key": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": "ASN-UNIT-004",
				"status": "Used",
			},
			"status",
			"Active",
			update_modified=True,
		)

	def test_on_purchase_receipt_trash_keeps_submitted_transition_logs(self):
		doc = SimpleNamespace(name="PR-UNIT-005", docstatus=1, asn="ASN-UNIT-005")

		with (
			patch("asn_module.handlers.purchase_receipt.frappe.db.delete") as delete,
			patch("asn_module.handlers.purchase_receipt.frappe.db.set_value") as set_value,
		):
			on_purchase_receipt_trash(doc, "on_trash")

		delete.assert_not_called()
		set_value.assert_not_called()

	def test_on_purchase_receipt_submit_skips_unmapped_pr_rows(self):
		asn = SimpleNamespace(name="ASN-UNIT-003", reload=lambda: None, update_receipt_status=lambda: None)
		doc = SimpleNamespace(
			asn="ASN-UNIT-003",
			asn_items='{"1": {}, "2": {"asn_item_name": "ASN-ITEM-002"}}',
			items=[
				SimpleNamespace(idx=1, qty=1, item_code="ITEM-001"),
				SimpleNamespace(idx=2, qty=2, item_code="ITEM-002"),
				SimpleNamespace(idx=3, qty=3, item_code="ITEM-003"),
			],
			name="PR-UNIT-003",
		)
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc", return_value=asn),
			patch("asn_module.handlers.purchase_receipt.frappe.db.sql") as sql,
			patch(
				"asn_module.handlers.purchase_receipt.frappe.get_all",
				return_value=[SimpleNamespace(name="ASN-ITEM-002", item_code="ITEM-002")],
			),
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition") as emit,
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZQ=="}),
			patch("asn_module.handlers.purchase_receipt.attach_qr_to_doc"),
			patch("asn_module.handlers.purchase_receipt.frappe.get_cached_value", return_value=True),
		):
			on_purchase_receipt_submit(doc, "on_submit")

		sql.assert_called_once()
		emit.assert_called_once()
		self.assertEqual(emit.call_args.kwargs["asn_item"], "ASN-ITEM-002")

	@patch("asn_module.handlers.purchase_receipt.attach_qr_to_doc")
	@patch("asn_module.qr_engine.generate.generate_qr")
	def test_submit_updates_asn_and_attaches_one_putaway_qr(self, generate_qr, attach_qr_to_doc):
		purchase_order = create_purchase_order_with_fiscal_dates(qty=10)
		asn = make_test_asn_with_two_items(purchase_order=purchase_order, qty=5)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		generate_qr.side_effect = [
			{"image_base64": "ZmFrZS1wdXJjaGFzZS1pbnZvaWNl"},
			{"image_base64": "ZmFrZS1wdXRhd2F5"},
		]

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
		self.assertEqual(generate_qr.call_count, 2)
		self.assertEqual(
			[action.kwargs["action"] for action in generate_qr.call_args_list],
			["create_purchase_invoice", "confirm_putaway"],
		)
		self.assertEqual(attach_qr_to_doc.call_count, 2)
		self.assertEqual(
			[call.args[2] for call in attach_qr_to_doc.call_args_list],
			["purchase-invoice-qr", f"putaway-{pr.name}"],
		)
