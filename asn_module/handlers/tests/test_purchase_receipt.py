from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	before_tests,
	create_purchase_order_with_fiscal_dates,
	make_test_asn,
	make_test_asn_with_two_items,
)
from asn_module.handlers.purchase_receipt import (
	asn_dispatch_action_key,
	create_gate_pass_from_asn,
	on_purchase_receipt_before_submit,
	on_purchase_receipt_submit,
	on_purchase_receipt_trash,
	stamp_asn_item_mapping,
)
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates
from asn_module.tests.integration.fixtures import pin_gate_pass_mode_for_tests, with_gate_pass_mode
from asn_module.utils.test_setup import make_test_breach


class TestCreatePurchaseReceipt(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		# Receipt-opening tests assume the fresh-site default (off); configured sites run it ON.
		pin_gate_pass_mode_for_tests(cls)

	def test_asn_dispatch_action_key_follows_gate_pass_mode(self):
		self.assertEqual(asn_dispatch_action_key(), "create_purchase_receipt")
		with with_gate_pass_mode(True):
			self.assertEqual(asn_dispatch_action_key(), "create_gate_pass_from_asn")

	def test_create_gate_pass_from_asn_follows_receipt_path_when_gate_pass_mode_is_off(self):
		asn = self._make_submitted_asn()
		result = create_gate_pass_from_asn("ASN", asn.name, {})
		self.assertEqual(result["doctype"], "Purchase Receipt")
		self.assertTrue(frappe.db.exists("Purchase Receipt", result["name"]))

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
		asn.submit()
		return asn

	def test_creates_draft_purchase_receipt_from_asn(self):
		asn = self._make_submitted_asn()

		result = create_gate_pass_from_asn(
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

		first = create_gate_pass_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		second = create_gate_pass_from_asn(
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
			create_gate_pass_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_rejects_asn_with_status_closed(self):
		asn = self._make_submitted_asn()
		frappe.db.set_value("ASN", asn.name, "status", "Closed", update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			create_gate_pass_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_rejects_draft_asn(self):
		purchase_order = create_purchase_order_with_fiscal_dates()
		asn = make_test_asn(purchase_order=purchase_order)
		asn.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			create_gate_pass_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_create_gate_pass_from_asn_returns_existing_draft_without_creating_new_doc(self):
		asn = SimpleNamespace(docstatus=1, status="Submitted", name="ASN-UNIT-001")
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc", return_value=asn),
			patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", return_value="PR-DRAFT-001"),
			patch("asn_module.handlers.purchase_receipt.frappe.new_doc") as new_doc,
		):
			result = create_gate_pass_from_asn("ASN", "ASN-UNIT-001", payload={})

		self.assertEqual(result["name"], "PR-DRAFT-001")
		self.assertIn("/app/purchase-receipt/PR-DRAFT-001", result["url"])
		new_doc.assert_not_called()

	def test_create_gate_pass_from_asn_builds_purchase_receipt_and_transition_logs(self):
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
			vehicle_number="MH12AB1234",
			driver_contact="9876543210",
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
					doctype="Purchase Receipt",
					company="TCPL",
					currency="INR",
					conversion_rate=1,
					title="{supplier_name}",
				)

			def insert(self, **kwargs):
				self.insert_kwargs = kwargs
				# Mimic Frappe: child names are assigned on insert, then after_insert hooks run.
				for pos, row in enumerate(self.items, start=1):
					row.name = f"new-pr-row-{pos}"
				stamp_asn_item_mapping(self)

		pr = _FakePurchaseReceipt()
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc", return_value=asn),
			patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", return_value=None),
			patch("asn_module.handlers.purchase_receipt.frappe.db.set_value") as set_value,
			patch("asn_module.handlers.purchase_receipt.make_purchase_receipt", return_value=pr) as make_pr,
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition") as emit,
		):
			result = create_gate_pass_from_asn("ASN", "ASN-UNIT-002", payload={})

		self.assertEqual(result["name"], "PR-UNIT-002")
		self.assertEqual(pr.supplier, "Supp-001")
		self.assertEqual(pr.title, "Supp-001")
		self.assertEqual(pr.company, "TCPL")
		self.assertEqual(pr.currency, "INR")
		self.assertEqual(pr.supplier_delivery_note, "INV-UNIT-002")
		self.assertEqual(pr.vehicle_no, "MH12AB1234")
		self.assertEqual(pr.driver_name, "9876543210")
		self.assertEqual(pr.items[0].purchase_order_item, "POI-001")
		self.assertEqual(pr.items[0].warehouse, "Stores - TCPL")
		self.assertEqual(pr.items[0].qty, 3)
		self.assertEqual(pr.items[0].amount, 75)
		self.assertEqual(
			pr.asn_items, '{"new-pr-row-1": {"asn_item_name": "ASN-ITEM-001", "original_qty": 3}}'
		)
		self.assertEqual(pr.insert_kwargs, {"ignore_permissions": True})
		set_value.assert_called_once_with(
			"Purchase Receipt", "PR-UNIT-002", "asn_items", pr.asn_items, update_modified=False
		)
		make_pr.assert_called_once_with("PO-001", args={"filtered_children": ["POI-001"]})
		emit.assert_called_once()

	def test_on_purchase_receipt_submit_skips_asn_bookkeeping_when_not_linked_to_asn(self):
		doc = SimpleNamespace(asn=None, is_return=0, name="PR-UNLINKED-UNIT", items=[])

		with (
			patch("asn_module.handlers.purchase_receipt.frappe.get_doc") as get_doc,
			patch("asn_module.handlers.purchase_receipt.store_scan_code") as store_scan_code_mock,
		):
			on_purchase_receipt_submit(doc, "on_submit")

		get_doc.assert_not_called()
		store_scan_code_mock.assert_called_once_with(doc, "create_purchase_invoice")

	def test_on_purchase_receipt_trash_deletes_draft_creation_transition_logs(self):
		doc = SimpleNamespace(name="PR-UNIT-004", docstatus=0, asn="ASN-UNIT-004")

		with patch("asn_module.handlers.purchase_receipt.frappe.db.delete") as delete:
			on_purchase_receipt_trash(doc, "on_trash")

		delete.assert_called_once_with(
			"ASN Transition Log",
			{
				"ref_doctype": "Purchase Receipt",
				"ref_name": "PR-UNIT-004",
				"state": "PR_CREATED_DRAFT",
			},
		)

	def test_on_purchase_receipt_trash_keeps_submitted_transition_logs(self):
		doc = SimpleNamespace(name="PR-UNIT-005", docstatus=1, asn="ASN-UNIT-005")

		with patch("asn_module.handlers.purchase_receipt.frappe.db.delete") as delete:
			on_purchase_receipt_trash(doc, "on_trash")

		delete.assert_not_called()

	def test_on_purchase_receipt_submit_skips_unmapped_pr_rows(self):
		asn = SimpleNamespace(name="ASN-UNIT-003", reload=lambda: None, update_receipt_status=lambda: None)
		doc = SimpleNamespace(
			asn="ASN-UNIT-003",
			asn_items='{"pr-row-1": {}, "pr-row-2": {"asn_item_name": "ASN-ITEM-002"}}',
			items=[
				SimpleNamespace(idx=1, name="pr-row-1", qty=1, item_code="ITEM-001"),
				SimpleNamespace(idx=2, name="pr-row-2", qty=2, item_code="ITEM-002"),
				SimpleNamespace(idx=3, name="pr-row-3", qty=3, item_code="ITEM-003"),
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
			patch("asn_module.handlers.purchase_receipt.store_scan_code"),
			patch("asn_module.handlers.purchase_receipt.frappe.get_cached_value", return_value=True),
		):
			on_purchase_receipt_submit(doc, "on_submit")

		sql.assert_called_once()
		emit.assert_called_once()
		self.assertEqual(emit.call_args.kwargs["asn_item"], "ASN-ITEM-002")

	@patch("asn_module.handlers.purchase_receipt.store_scan_code")
	def test_submit_updates_asn_and_attaches_invoice_scan_code(self, store_scan_code_mock):
		purchase_order = create_purchase_order_with_fiscal_dates(qty=10)
		asn = make_test_asn_with_two_items(purchase_order=purchase_order, qty=5)
		asn.insert(ignore_permissions=True)
		asn.submit()

		result = create_gate_pass_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		pr = frappe.get_doc("Purchase Receipt", result["name"])

		pr.submit()
		asn.reload()

		self.assertEqual(asn.status, "Received")
		self.assertEqual([row.received_qty for row in asn.items], [5, 5])
		self.assertEqual([row.discrepancy_qty for row in asn.items], [0, 0])
		self.assertEqual(
			[call.args[1] for call in store_scan_code_mock.call_args_list],
			["create_purchase_invoice"],
		)

	@patch("asn_module.handlers.purchase_receipt.store_scan_code")
	def test_mixed_inspection_receipt_gets_only_invoice_code(self, store_scan_code_mock):
		"""An inspection-required item changes nothing: the receipt carries the invoice code only."""
		purchase_order = create_purchase_order_with_fiscal_dates(qty=10, item_count=2, unique_items=True)
		frappe.db.set_value(
			"Item",
			purchase_order.items[1].item_code,
			"inspection_required_before_purchase",
			1,
			update_modified=False,
		)
		asn = make_test_asn(purchase_order=purchase_order, qty=5)
		second_row = purchase_order.items[1]
		asn.append(
			"items",
			{
				"purchase_order": purchase_order.name,
				"purchase_order_item": second_row.name,
				"item_code": second_row.item_code,
				"qty": 5,
				"uom": second_row.uom,
				"rate": second_row.rate,
			},
		)
		asn.insert(ignore_permissions=True)
		asn.submit()

		result = create_gate_pass_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(len(pr.items), 2)

		# The inspection-required row gates PR submit: a real mixed receipt only
		# reaches the follow-up codes once its Quality Inspection exists.
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr.name,
				"item_code": second_row.item_code,
				"sample_size": 1,
				"status": "Accepted",
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
			}
		)
		qi.insert(ignore_permissions=True)
		qi.submit()
		pr.reload()  # the QI links itself onto the receipt row server-side

		pr.submit()

		self.assertEqual(
			[call.args[1] for call in store_scan_code_mock.call_args_list],
			["create_purchase_invoice"],
		)


class TestPurchaseReceiptStockCap(FrappeTestCase):
	def _breach(self):
		return make_test_breach()

	def test_submit_is_blocked_when_cap_is_breached(self):
		doc = SimpleNamespace(name="PR-0001", is_return=0, branch="Mumbai", asn=None, items=[])
		with patch(
			"asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt",
			return_value=[self._breach()],
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				on_purchase_receipt_before_submit(doc)
		self.assertIn("WIDGET", str(ctx.exception))

	def test_submit_is_allowed_when_no_breach(self):
		doc = SimpleNamespace(name="PR-0002", is_return=0, branch="Mumbai", asn=None, items=[])
		with patch("asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt", return_value=[]):
			self.assertIsNone(on_purchase_receipt_before_submit(doc))

	def test_handler_passes_the_receipt_through_for_asn_exclusion(self):
		doc = SimpleNamespace(name="PR-0003", is_return=0, branch="Mumbai", asn="ASN-0007", items=[])
		with patch(
			"asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt", return_value=[]
		) as spy:
			on_purchase_receipt_before_submit(doc)
		spy.assert_called_once_with(doc)
