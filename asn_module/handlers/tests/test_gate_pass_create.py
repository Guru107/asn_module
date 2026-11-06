from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from asn_module.handlers.gate_pass_create import (
	collect_receive_qty_by_po_item,
	create_from_gate_pass,
	ensure_load_after_mapping,
	map_purchase_receipt_draft_from_gate_pass,
	overlay_gate_pass_onto_mapped_pr,
	throw_if_open_purchase_receipt_for_gate_pass,
	validate_gate_pass_for_purchase_receipt,
)


def _gp(**kwargs):
	defaults = dict(
		name="26-27/1",
		docstatus=1,
		entry_type="Gate In",
		document_reference="Purchase Order",
		reference_number="PO-1",
		vehicle_number="MH12XY9999",
		driver_name="In Driver",
		company="TCPL",
		branch="Main Branch",
		supplier="SUP-1",
		invoice_number="INV-1",
		invoice_date="2026-09-19",
		challan_number="CH-1",
		challan_date="2026-09-19",
		gate_pass_type="Material",
		items=[],
	)
	defaults.update(kwargs)
	return SimpleNamespace(**defaults)


def _row(**kwargs):
	return SimpleNamespace(**kwargs)


class TestCollectReceiveQty(TestCase):
	def test_skips_zero_and_maps_receive_qty(self):
		gp = _gp(
			items=[
				_row(name="r1", purchase_order_item="poi-a", receive_qty=20),
				_row(name="r2", purchase_order_item="poi-b", receive_qty=0),
				_row(name="r3", purchase_order_item="poi-c", receive_qty=5),
			],
		)
		qty_map, row_map = collect_receive_qty_by_po_item(gp)
		self.assertEqual(qty_map, {"poi-a": 20.0, "poi-c": 5.0})
		self.assertEqual(row_map["poi-a"].name, "r1")

	def test_reads_recieve_qty_typo_and_dict_rows(self):
		gp = {
			"items": [
				{"purchase_order_item": "poi-a", "recieve_qty": 7},
				{"purchase_order_item": "", "receive_qty": 5},
			]
		}
		qty_map, row_map = collect_receive_qty_by_po_item(gp)
		self.assertEqual(qty_map, {"poi-a": 7.0})
		self.assertEqual(row_map["poi-a"]["purchase_order_item"], "poi-a")


class TestEnsureLoadAfterMapping(TestCase):
	def test_sets_onload_dict_when_set_onload_missing(self):
		doc = SimpleNamespace()
		ensure_load_after_mapping(doc)
		self.assertTrue(doc._onload["load_after_mapping"])

	def test_merges_into_existing_onload_dict(self):
		doc = SimpleNamespace(_onload={"other": 1})
		ensure_load_after_mapping(doc)
		self.assertTrue(doc._onload["load_after_mapping"])
		self.assertEqual(doc._onload["other"], 1)


class TestValidateGatePassForPurchaseReceipt(TestCase):
	def test_requires_submitted_gate_in_po_reference(self):
		with self.assertRaises(frappe.ValidationError):
			validate_gate_pass_for_purchase_receipt(_gp(docstatus=0))
		with self.assertRaises(frappe.ValidationError):
			validate_gate_pass_for_purchase_receipt(_gp(entry_type="Gate Out"))
		with self.assertRaises(frappe.ValidationError):
			validate_gate_pass_for_purchase_receipt(_gp(document_reference="Sales Order"))


class TestThrowIfOpenPurchaseReceipt(FrappeTestCase):
	def test_no_op_when_custom_field_missing(self):
		meta = SimpleNamespace(has_field=lambda _field: False)
		with patch("asn_module.handlers.gate_pass_create.frappe.get_meta", return_value=meta):
			throw_if_open_purchase_receipt_for_gate_pass("GP-1")

	def test_raises_when_draft_pr_exists(self):
		meta = SimpleNamespace(has_field=lambda field: field == "custom_gate_pass_reference")
		with (
			patch("asn_module.handlers.gate_pass_create.frappe.get_meta", return_value=meta),
			patch(
				"asn_module.handlers.gate_pass_create.frappe.get_all",
				return_value=[{"name": "PR-OPEN-1"}],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				throw_if_open_purchase_receipt_for_gate_pass("GP-1")


class TestMapPurchaseReceiptDraftHelpers(FrappeTestCase):
	def test_raises_when_no_receive_qty_lines(self):
		gp = _gp(items=[_row(purchase_order_item="poi-a", receive_qty=0)])
		with self.assertRaises(frappe.ValidationError):
			map_purchase_receipt_draft_from_gate_pass(gp)

	def test_create_from_gate_pass_requires_name(self):
		with self.assertRaises(frappe.ValidationError):
			create_from_gate_pass("")

	def test_create_from_gate_pass_rejects_unmapped_entry_type(self):
		gp = _gp(entry_type="Gate Out", document_reference="Sales Order")
		with patch("asn_module.handlers.gate_pass_create.frappe.get_doc", return_value=gp):
			with self.assertRaises(frappe.ValidationError):
				create_from_gate_pass("GP-1")

	def test_sets_header_back_link_invoice_and_receive_qty(self):
		gp = _gp(
			items=[_row(name="gp-item-1", purchase_order_item="poi-a", receive_qty=20)],
		)
		pr = SimpleNamespace(
			branch=None,
			items=[
				SimpleNamespace(
					purchase_order_item="poi-a",
					qty=100,
					received_qty=0,
					stock_qty=0,
					conversion_factor=1,
					custom_gate_pass=None,
					custom_gate_pass_item=None,
					branch=None,
				)
			],
		)
		overlay_gate_pass_onto_mapped_pr(pr, gp)
		self.assertEqual(pr.custom_gate_pass_reference, "26-27/1")
		self.assertEqual(pr.custom_invoice_no, "INV-1")
		self.assertEqual(pr.branch, "Main Branch")
		self.assertEqual(pr.items[0].qty, 20)
		self.assertEqual(pr.items[0].received_qty, 20)
		self.assertEqual(pr.items[0].custom_gate_pass, "26-27/1")
		self.assertEqual(pr.items[0].custom_gate_pass_item, "gp-item-1")


class TestMapPurchaseReceiptDraft(FrappeTestCase):
	def test_whitelisted_create_from_gate_pass_returns_unsaved_doc(self):
		if not frappe.db.exists("DocType", "Gate Pass"):
			self.skipTest("Gate Pass not installed")
		from asn_module.asn_module.doctype.asn.test_asn import (
			before_tests,
			create_purchase_order,
			make_test_asn,
		)
		from asn_module.handlers.gate_pass_create import create_from_gate_pass
		from asn_module.handlers.purchase_receipt import _open_or_create_material_gate_pass
		from asn_module.tests.integration.fixtures import integration_user_context

		before_tests()
		with integration_user_context():
			purchase_order = create_purchase_order(qty=3)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"GP-MAP-{frappe.generate_hash(length=8)}",
				qty=3,
			)
			asn.insert(ignore_permissions=True)
			asn.submit()
			opened = _open_or_create_material_gate_pass(asn)
			gate_pass = frappe.get_doc("Gate Pass", opened["name"])
			overlay_branch = "Overlay Branch"
			if frappe.get_meta("Gate Pass").has_field("branch"):
				gate_pass.db_set("branch", overlay_branch, update_modified=False)
				gate_pass.reload()
			frappe.db.set_value("Gate Pass", gate_pass.name, "docstatus", 1, update_modified=False)
			gate_pass.reload()

			create_from_gate_pass(gate_pass.name)
			doc = frappe.response.get("message")
			self.assertEqual(doc.doctype, "Purchase Receipt")
			self.assertFalse(doc.name)
			self.assertEqual(flt(doc.items[0].qty), 3)
			if frappe.get_meta("Purchase Receipt").has_field("custom_gate_pass_reference"):
				self.assertEqual(doc.custom_gate_pass_reference, gate_pass.name)
			if frappe.get_meta("Purchase Receipt").has_field("branch") and frappe.get_meta(
				"Gate Pass"
			).has_field("branch"):
				self.assertEqual(doc.branch, overlay_branch)
