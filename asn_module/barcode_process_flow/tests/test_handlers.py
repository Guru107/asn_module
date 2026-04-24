from types import SimpleNamespace
from unittest.mock import patch

import frappe

from asn_module.barcode_process_flow import handlers
from asn_module.tests.compat import UnitTestCase


class TestFlowHandlers(UnitTestCase):
	def test_material_request_to_purchase_order(self):
		doc = SimpleNamespace(name="PO-1", doctype="Purchase Order", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_purchase_order",
			return_value=doc,
		):
			result = handlers.material_request_to_purchase_order("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Purchase Order")
		self.assertEqual(result["name"], "PO-1")

	def test_material_request_to_rfq(self):
		doc = SimpleNamespace(name="RFQ-1", doctype="Request for Quotation", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_request_for_quotation",
			return_value=doc,
		):
			result = handlers.material_request_to_rfq("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Request for Quotation")

	def test_material_request_to_supplier_quotation(self):
		doc = SimpleNamespace(name="SQ-1", doctype="Supplier Quotation", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_supplier_quotation",
			return_value=doc,
		):
			result = handlers.material_request_to_supplier_quotation("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Supplier Quotation")

	def test_material_request_to_stock_entry(self):
		doc = SimpleNamespace(name="STE-1", doctype="Stock Entry", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_stock_entry",
			return_value=doc,
		):
			result = handlers.material_request_to_stock_entry("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Stock Entry")

	def test_material_request_to_in_transit_stock_entry_requires_warehouse(self):
		with self.assertRaises(frappe.ValidationError):
			handlers.material_request_to_in_transit_stock_entry("Material Request", "MR-1", {})

		doc = SimpleNamespace(name="STE-2", doctype="Stock Entry", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_in_transit_stock_entry",
			return_value=doc,
		) as make_in_transit:
			result = handlers.material_request_to_in_transit_stock_entry(
				"Material Request",
				"MR-1",
				{"in_transit_warehouse": "Transit - TCPL"},
			)
		make_in_transit.assert_called_once_with("MR-1", "Transit - TCPL")
		self.assertEqual(result["name"], "STE-2")

	def test_material_request_to_work_order(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch(
				"erpnext.stock.doctype.material_request.material_request.raise_work_orders",
				return_value=["WO-1"],
			),
		):
			result = handlers.material_request_to_work_order("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Work Order")
		self.assertEqual(result["name"], "WO-1")

		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch(
				"erpnext.stock.doctype.material_request.material_request.raise_work_orders",
				return_value=[],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_work_order("Material Request", "MR-1", {})

	def test_material_request_to_pick_list(self):
		doc = SimpleNamespace(name="PICK-1", doctype="Pick List", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.create_pick_list",
			return_value=doc,
		):
			result = handlers.material_request_to_pick_list("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Pick List")

	def test_asn_to_subcontracting_receipt_handler(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(subcontracting_order="SCO-1"),
			),
			patch(
				"asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
				return_value={
					"doctype": "Subcontracting Receipt",
					"name": "SCR-1",
					"url": "/app/subcontracting-receipt/SCR-1",
				},
			) as create_receipt,
		):
			result = handlers.create_subcontracting_receipt_from_asn("ASN", "ASN-1", {})
		create_receipt.assert_called_once()
		self.assertEqual(result["doctype"], "Subcontracting Receipt")

		with patch(
			"asn_module.barcode_process_flow.handlers.frappe.get_doc",
			return_value=SimpleNamespace(subcontracting_order=""),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.create_subcontracting_receipt_from_asn("ASN", "ASN-1", {})

	def test_internal_contract_helpers(self):
		self.assertEqual(handlers._doc_contract("Purchase Order", "PO-1")["url"], "/app/purchase_order/PO-1")
		doc = SimpleNamespace(name="", doctype="Purchase Order")
		doc.insert = lambda **_: setattr(doc, "name", "PO-2")
		contract = handlers._insert_and_contract(doc, "Purchase Order")
		self.assertEqual(contract["name"], "PO-2")
		self.assertEqual(handlers._insert_and_contract("PO-3", "Purchase Order")["name"], "PO-3")
