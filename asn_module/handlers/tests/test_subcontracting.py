from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
from asn_module.handlers.subcontracting import (
	create_dispatch_from_subcontracting_order,
	create_receipt_from_subcontracting_order,
	on_subcontracting_dispatch_submit,
	on_subcontracting_order_submit,
)


class _FakeDoc:
	def __init__(self, name):
		self.name = name
		self.insert_calls = 0

	def insert(self, ignore_permissions=False):
		self.insert_calls += 1
		if not self.name:
			self.name = f"FAKE-{self.insert_calls}"
		return self


class TestSubcontractingHandlers(FrappeTestCase):
	def _ensure_item(self, item_code: str, *, is_stock_item: int = 1):
		if frappe.db.exists("Item", item_code):
			return item_code

		item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
		uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": uom,
				"is_stock_item": is_stock_item,
				"is_sub_contracted_item": 1 if is_stock_item else 0,
			}
		)
		item.insert(ignore_permissions=True)
		return item_code

	def _ensure_warehouse(self, warehouse_name: str, company: str) -> str:
		existing = frappe.db.get_value(
			"Warehouse",
			{"warehouse_name": warehouse_name, "company": company},
			"name",
		)
		if existing:
			return existing

		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": company,
			}
		)
		warehouse.insert(ignore_permissions=True)
		return warehouse.name

	def _ensure_bom(self, fg_item: str, rm_item: str, company: str, uom: str) -> str:
		existing = frappe.db.get_value("BOM", {"item": fg_item, "is_active": 1, "is_default": 1}, "name")
		if existing:
			return existing

		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg_item,
				"company": company,
				"quantity": 1,
				"uom": uom,
				"items": [
					{
						"item_code": rm_item,
						"qty": 1,
						"uom": uom,
						"rate": 5,
					}
				],
			}
		)
		bom.insert(ignore_permissions=True)
		bom.submit()
		return bom.name

	def _make_integration_subcontracting_order(self, company: str | None = None):
		po = create_purchase_order()
		company = company or po.company
		source_warehouse = self._ensure_warehouse("_Test Subcontract Source Warehouse", company)
		supplier_warehouse = self._ensure_warehouse("_Test Subcontract Supplier Warehouse", company)
		for row in po.items:
			if row.warehouse == source_warehouse:
				continue
			frappe.db.set_value(
				"Purchase Order Item",
				row.name,
				"warehouse",
				source_warehouse,
				update_modified=False,
			)
		po.reload()
		supplier = po.supplier
		uom = po.items[0].uom

		fg_item = self._ensure_item("_Test Subcontract FG Item")
		service_item = self._ensure_item("_Test Subcontract Service Item", is_stock_item=0)
		rm_item = self._ensure_item("_Test Subcontract RM Item")
		frappe.db.set_value("Item", rm_item, "valuation_rate", 5)
		bom = self._ensure_bom(fg_item, rm_item, company, uom)

		sco = frappe.get_doc(
			{
				"doctype": "Subcontracting Order",
				"purchase_order": po.name,
				"supplier": supplier,
				"supplier_name": supplier,
				"supplier_warehouse": supplier_warehouse,
				"company": company,
				"transaction_date": nowdate(),
				"status": "Open",
				"items": [
					{
						"item_code": fg_item,
						"item_name": fg_item,
						"bom": bom,
						"qty": 2,
						"stock_uom": uom,
						"rate": 100,
						"amount": 200,
						"warehouse": source_warehouse,
						"purchase_order_item": po.items[0].name,
						"received_qty": 0,
					}
				],
				"service_items": [
					{
						"item_code": service_item,
						"qty": 2,
						"rate": 10,
						"amount": 20,
						"fg_item": fg_item,
						"fg_item_qty": 2,
						"warehouse": source_warehouse,
						"purchase_order_item": po.items[0].name,
					}
				],
				"supplied_items": [
					{
						"main_item_code": fg_item,
						"rm_item_code": rm_item,
						"stock_uom": uom,
						"reserve_warehouse": source_warehouse,
						"required_qty": 2,
						"total_supplied_qty": 0,
						"rate": 5,
					}
				],
			}
		)

		with patch(
			"erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order.SubcontractingOrder.validate"
		):
			sco.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Subcontracting Order", sco.name, "docstatus", 1, update_modified=False)
		frappe.db.set_value("Subcontracting Order", sco.name, "status", "Open", update_modified=False)
		return frappe.get_doc("Subcontracting Order", sco.name)

	def test_create_dispatch_creates_draft_stock_entry(self):
		sco = frappe._dict(name="SCO-0001", docstatus=1)
		stock_entry = _FakeDoc(name="STE-0001")

		with (
			patch("asn_module.handlers.subcontracting.frappe.get_doc", return_value=sco),
			patch("asn_module.handlers.subcontracting.frappe.new_doc", return_value=stock_entry),
			patch(
				"erpnext.controllers.subcontracting_controller.make_rm_stock_entry",
				return_value=stock_entry,
			) as make_rm,
		):
			result = create_dispatch_from_subcontracting_order(
				source_doctype="Subcontracting Order",
				source_name=sco.name,
				payload={"action": "create_subcontracting_dispatch"},
			)

		make_rm.assert_called_once()
		self.assertEqual(stock_entry.insert_calls, 1)
		self.assertEqual(result["doctype"], "Stock Entry")
		self.assertEqual(result["name"], "STE-0001")
		self.assertEqual(result["url"], "/app/stock-entry/STE-0001")
		self.assertIn("Send to Subcontractor", result["message"])

	def test_create_dispatch_rejects_unsubmitted_sco(self):
		sco = frappe._dict(name="SCO-0001", docstatus=0)

		with patch("asn_module.handlers.subcontracting.frappe.get_doc", return_value=sco):
			with self.assertRaises(frappe.ValidationError):
				create_dispatch_from_subcontracting_order(
					source_doctype="Subcontracting Order",
					source_name=sco.name,
					payload={"action": "create_subcontracting_dispatch"},
				)

	def test_create_receipt_creates_draft_subcontracting_receipt(self):
		sco = frappe._dict(name="SCO-0001", docstatus=1)
		scr = _FakeDoc(name="SCR-0001")

		with (
			patch("asn_module.handlers.subcontracting.frappe.get_doc", return_value=sco),
			patch(
				"erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order.make_subcontracting_receipt",
				return_value=scr,
			) as make_scr,
		):
			result = create_receipt_from_subcontracting_order(
				source_doctype="Subcontracting Order",
				source_name=sco.name,
				payload={"action": "create_subcontracting_receipt"},
			)

		make_scr.assert_called_once_with(sco.name)
		self.assertEqual(scr.insert_calls, 1)
		self.assertEqual(result["doctype"], "Subcontracting Receipt")
		self.assertEqual(result["name"], "SCR-0001")
		self.assertEqual(result["url"], "/app/subcontracting-receipt/SCR-0001")

	def test_create_receipt_rejects_unsubmitted_sco(self):
		sco = frappe._dict(name="SCO-0001", docstatus=0)

		with patch("asn_module.handlers.subcontracting.frappe.get_doc", return_value=sco):
			with self.assertRaises(frappe.ValidationError):
				create_receipt_from_subcontracting_order(
					source_doctype="Subcontracting Order",
					source_name=sco.name,
					payload={"action": "create_subcontracting_receipt"},
				)

	def test_on_subcontracting_order_submit_attaches_dispatch_qr(self):
		doc = frappe._dict(doctype="Subcontracting Order", name="SCO-0001")
		qr_result = {"image_base64": "ZmFrZS1xcg=="}

		with (
			patch("asn_module.handlers.subcontracting.generate_qr", return_value=qr_result) as generate,
			patch("asn_module.handlers.subcontracting.attach_qr_to_doc") as attach,
		):
			on_subcontracting_order_submit(doc, "on_submit")

		generate.assert_called_once_with(
			action="create_subcontracting_dispatch",
			source_doctype="Subcontracting Order",
			source_name="SCO-0001",
		)
		attach.assert_called_once_with(doc, qr_result, "subcontracting-dispatch-qr")

	def test_on_subcontracting_dispatch_submit_attaches_receipt_qr(self):
		doc = frappe._dict(
			doctype="Stock Entry",
			name="STE-0001",
			stock_entry_type="Send to Subcontractor",
			subcontracting_order="SCO-0001",
		)
		qr_result = {"image_base64": "ZmFrZS1xcg=="}

		with (
			patch("asn_module.handlers.subcontracting.generate_qr", return_value=qr_result) as generate,
			patch("asn_module.handlers.subcontracting.attach_qr_to_doc") as attach,
		):
			on_subcontracting_dispatch_submit(doc, "on_submit")

		generate.assert_called_once_with(
			action="create_subcontracting_receipt",
			source_doctype="Subcontracting Order",
			source_name="SCO-0001",
		)
		attach.assert_called_once_with(doc, qr_result, "subcontracting-receipt-qr")

	def test_on_subcontracting_dispatch_submit_ignores_non_dispatch_stock_entry(self):
		doc = frappe._dict(
			doctype="Stock Entry",
			name="STE-0001",
			stock_entry_type="Material Transfer",
			subcontracting_order="SCO-0001",
		)

		with (
			patch("asn_module.handlers.subcontracting.generate_qr") as generate,
			patch("asn_module.handlers.subcontracting.attach_qr_to_doc") as attach,
		):
			on_subcontracting_dispatch_submit(doc, "on_submit")

		generate.assert_not_called()
		attach.assert_not_called()

	def test_on_subcontracting_dispatch_submit_ignores_missing_subcontracting_order(self):
		doc = frappe._dict(
			doctype="Stock Entry",
			name="STE-0001",
			stock_entry_type="Send to Subcontractor",
			subcontracting_order="",
		)

		with (
			patch("asn_module.handlers.subcontracting.generate_qr") as generate,
			patch("asn_module.handlers.subcontracting.attach_qr_to_doc") as attach,
		):
			on_subcontracting_dispatch_submit(doc, "on_submit")

		generate.assert_not_called()
		attach.assert_not_called()

	def test_create_dispatch_integration_creates_real_draft_stock_entry(self):
		sco = self._make_integration_subcontracting_order()

		result = create_dispatch_from_subcontracting_order(
			source_doctype="Subcontracting Order",
			source_name=sco.name,
			payload={"action": "create_subcontracting_dispatch"},
		)

		self.assertEqual(result["doctype"], "Stock Entry")
		stock_entry = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(stock_entry.docstatus, 0)
		self.assertEqual(stock_entry.stock_entry_type, "Send to Subcontractor")
		self.assertEqual(stock_entry.subcontracting_order, sco.name)
		self.assertTrue(stock_entry.items)

	def test_create_receipt_integration_creates_real_draft_subcontracting_receipt(self):
		sco = self._make_integration_subcontracting_order()
		with patch("erpnext.controllers.subcontracting_controller.get_incoming_rate", return_value=5):
			result = create_receipt_from_subcontracting_order(
				source_doctype="Subcontracting Order",
				source_name=sco.name,
				payload={"action": "create_subcontracting_receipt"},
			)

		self.assertEqual(result["doctype"], "Subcontracting Receipt")
		scr = frappe.get_doc("Subcontracting Receipt", result["name"])
		self.assertEqual(scr.docstatus, 0)
		self.assertTrue(scr.items)
		self.assertEqual(scr.items[0].subcontracting_order, sco.name)
