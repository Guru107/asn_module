from types import SimpleNamespace
from unittest.mock import patch

import frappe

from asn_module.barcode_process_flow import handlers
from asn_module.tests.compat import UnitTestCase


class TestFlowHandlers(UnitTestCase):
	def test_material_request_to_purchase_order_uses_payload_supplier(self):
		doc = SimpleNamespace(
			name="PO-1",
			doctype="Purchase Order",
			supplier="",
			insert=lambda **_: None,
			set_missing_values=lambda: None,
		)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_purchase_order",
			return_value=doc,
		):
			result = handlers.material_request_to_purchase_order(
				"Material Request", "MR-1", {"supplier": "Supp-1"}
			)
		self.assertEqual(doc.supplier, "Supp-1")
		self.assertEqual(result["doctype"], "Purchase Order")
		self.assertEqual(result["name"], "PO-1")

	def test_material_request_to_purchase_order_uses_resolved_supplier(self):
		doc = SimpleNamespace(
			name="PO-2",
			doctype="Purchase Order",
			supplier="",
			insert=lambda **_: None,
			set_missing_values=lambda: None,
		)
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_purchase_order",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_material_request_supplier",
				return_value="Supp-2",
			) as resolve_supplier,
		):
			result = handlers.material_request_to_purchase_order("Material Request", "MR-1", {})
		resolve_supplier.assert_called_once_with("MR-1")
		self.assertEqual(doc.supplier, "Supp-2")
		self.assertEqual(result["doctype"], "Purchase Order")
		self.assertEqual(result["name"], "PO-2")

	def test_material_request_to_purchase_order_requires_supplier(self):
		doc = SimpleNamespace(
			name="PO-3",
			doctype="Purchase Order",
			supplier="",
			insert=lambda **_: None,
			set_missing_values=lambda: None,
		)
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_purchase_order",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_material_request_supplier",
				return_value="",
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_purchase_order("Material Request", "MR-1", {})

	def test_material_request_to_rfq(self):
		class _RFQDoc:
			def __init__(self):
				self.name = "RFQ-1"
				self.doctype = "Request for Quotation"
				self.suppliers = []

			def append(self, fieldname, row):
				if fieldname == "suppliers":
					self.suppliers.append(SimpleNamespace(**row))

			def insert(self, **_kwargs):
				return None

		doc = _RFQDoc()
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_request_for_quotation",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_supplier_for_material_request",
				return_value="Supp-1",
			),
		):
			result = handlers.material_request_to_rfq("Material Request", "MR-1", {})
		self.assertEqual(len(doc.suppliers), 1)
		self.assertEqual(doc.suppliers[0].supplier, "Supp-1")
		self.assertEqual(result["doctype"], "Request for Quotation")

	def test_material_request_to_rfq_requires_supplier(self):
		doc = SimpleNamespace(
			name="RFQ-2",
			doctype="Request for Quotation",
			suppliers=[],
			insert=lambda **_: None,
		)
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_request_for_quotation",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_supplier_for_material_request",
				return_value="",
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_rfq("Material Request", "MR-1", {})

	def test_material_request_to_supplier_quotation(self):
		doc = SimpleNamespace(
			name="SQ-1",
			doctype="Supplier Quotation",
			supplier="",
			insert=lambda **_: None,
		)
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_supplier_quotation",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_supplier_for_material_request",
				return_value="Supp-1",
			),
		):
			result = handlers.material_request_to_supplier_quotation("Material Request", "MR-1", {})
		self.assertEqual(doc.supplier, "Supp-1")
		self.assertEqual(result["doctype"], "Supplier Quotation")

	def test_material_request_to_supplier_quotation_requires_supplier(self):
		doc = SimpleNamespace(
			name="SQ-2",
			doctype="Supplier Quotation",
			supplier="",
			insert=lambda **_: None,
		)
		with (
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_supplier_quotation",
				return_value=doc,
			),
			patch(
				"asn_module.barcode_process_flow.handlers._resolve_supplier_for_material_request",
				return_value="",
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_supplier_quotation("Material Request", "MR-1", {})

	def test_material_request_to_stock_entry(self):
		doc = SimpleNamespace(name="STE-1", doctype="Stock Entry", insert=lambda **_: None)
		with patch(
			"erpnext.stock.doctype.material_request.material_request.make_stock_entry",
			return_value=doc,
		):
			result = handlers.material_request_to_stock_entry("Material Request", "MR-1", {})
		self.assertEqual(result["doctype"], "Stock Entry")

	def test_material_request_to_in_transit_stock_entry_requires_warehouse(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch("asn_module.barcode_process_flow.handlers.frappe.db.get_value", return_value=""),
			patch("asn_module.barcode_process_flow.handlers.frappe.get_all", return_value=[]),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_in_transit_stock_entry("Material Request", "MR-1", {})

		doc = SimpleNamespace(name="STE-2", doctype="Stock Entry", insert=lambda **_: None)
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_in_transit_stock_entry",
				return_value=doc,
			) as make_in_transit,
		):
			result = handlers.material_request_to_in_transit_stock_entry(
				"Material Request",
				"MR-1",
				{"in_transit_warehouse": "Transit - TCPL"},
			)
		make_in_transit.assert_called_once_with("MR-1", "Transit - TCPL")
		self.assertEqual(result["name"], "STE-2")

		doc_fallback = SimpleNamespace(name="STE-3", doctype="Stock Entry", insert=lambda **_: None)
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.db.get_value",
				return_value="Transit - TCPL",
			),
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_in_transit_stock_entry",
				return_value=doc_fallback,
			) as make_in_transit_fallback,
		):
			result_fallback = handlers.material_request_to_in_transit_stock_entry(
				"Material Request",
				"MR-1",
				{},
			)

		make_in_transit_fallback.assert_called_once_with("MR-1", "Transit - TCPL")
		self.assertEqual(result_fallback["name"], "STE-3")

		doc_transit = SimpleNamespace(name="STE-4", doctype="Stock Entry", insert=lambda **_: None)
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch("asn_module.barcode_process_flow.handlers.frappe.db.get_value", return_value=""),
			patch("asn_module.barcode_process_flow.handlers.frappe.get_all", return_value=["Transit - TCPL"]),
			patch(
				"erpnext.stock.doctype.material_request.material_request.make_in_transit_stock_entry",
				return_value=doc_transit,
			) as make_transit_single,
		):
			result_transit = handlers.material_request_to_in_transit_stock_entry("Material Request", "MR-1", {})
		make_transit_single.assert_called_once_with("MR-1", "Transit - TCPL")
		self.assertEqual(result_transit["name"], "STE-4")

		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(company="TCPL"),
			),
			patch("asn_module.barcode_process_flow.handlers.frappe.db.get_value", return_value=""),
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_all",
				return_value=["Transit A - TCPL", "Transit B - TCPL"],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.material_request_to_in_transit_stock_entry("Material Request", "MR-1", {})

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
		create_receipt.assert_called_once_with(
			source_doctype="Subcontracting Order",
			source_name="SCO-1",
			payload={},
		)
		self.assertEqual(result["doctype"], "Subcontracting Receipt")

		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(
					subcontracting_order="",
					items=[SimpleNamespace(purchase_order="PO-1")],
				),
			),
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_all",
				return_value=[{"name": "SCO-2"}],
			),
			patch(
				"asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
				return_value={
					"doctype": "Subcontracting Receipt",
					"name": "SCR-2",
					"url": "/app/subcontracting-receipt/SCR-2",
				},
			) as create_receipt_from_po,
		):
			fallback_result = handlers.create_subcontracting_receipt_from_asn("ASN", "ASN-2", {})
		create_receipt_from_po.assert_called_once_with(
			source_doctype="Subcontracting Order",
			source_name="SCO-2",
			payload={},
		)
		self.assertEqual(fallback_result["name"], "SCR-2")

		with patch(
			"asn_module.barcode_process_flow.handlers.frappe.get_doc",
			return_value=SimpleNamespace(subcontracting_order="", items=[]),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers.create_subcontracting_receipt_from_asn("ASN", "ASN-1", {})

	def test_resolve_material_request_supplier_from_item_defaults(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(
					company="TCPL",
					items=[SimpleNamespace(item_code="ITEM-1"), SimpleNamespace(item_code="ITEM-1")],
				),
			),
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_all",
				side_effect=[
					[{"parent": "ITEM-1", "default_supplier": "Supp-1"}],
					[],
				],
			),
		):
			self.assertEqual(handlers._resolve_material_request_supplier("MR-1"), "Supp-1")

	def test_resolve_material_request_supplier_ambiguous(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(
					company="TCPL",
					items=[SimpleNamespace(item_code="ITEM-1"), SimpleNamespace(item_code="ITEM-2")],
				),
			),
				patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_all",
				side_effect=[
					[],
					[
						{"parent": "ITEM-1", "supplier": "Supp-1"},
						{"parent": "ITEM-2", "supplier": "Supp-2"},
					],
				],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers._resolve_material_request_supplier("MR-1")

	def test_resolve_material_request_supplier_rejects_multi_supplier_item(self):
		with (
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_doc",
				return_value=SimpleNamespace(
					company="TCPL",
					items=[SimpleNamespace(item_code="ITEM-1")],
				),
			),
			patch(
				"asn_module.barcode_process_flow.handlers.frappe.get_all",
				side_effect=[
					[],
					[
						{"parent": "ITEM-1", "supplier": "Supp-1"},
						{"parent": "ITEM-1", "supplier": "Supp-2"},
					],
				],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				handlers._resolve_material_request_supplier("MR-1")

	def test_internal_contract_helpers(self):
		self.assertEqual(handlers._doc_contract("Purchase Order", "PO-1")["url"], "/app/purchase_order/PO-1")
		doc = SimpleNamespace(name="", doctype="Purchase Order")
		doc.is_new = lambda: True
		doc.insert = lambda **_: setattr(doc, "name", "PO-2")
		contract = handlers._insert_and_contract(doc, "Purchase Order")
		self.assertEqual(contract["name"], "PO-2")
		self.assertEqual(handlers._insert_and_contract("PO-3", "Purchase Order")["name"], "PO-3")
