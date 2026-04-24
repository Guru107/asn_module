from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def material_request_to_purchase_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order

	doc = make_purchase_order(source_name)
	return _insert_and_contract(doc, "Purchase Order")


def material_request_to_rfq(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import make_request_for_quotation

	doc = make_request_for_quotation(source_name)
	return _insert_and_contract(doc, "Request for Quotation")


def material_request_to_supplier_quotation(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import make_supplier_quotation

	doc = make_supplier_quotation(source_name)
	return _insert_and_contract(doc, "Supplier Quotation")


def material_request_to_stock_entry(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import make_stock_entry

	doc = make_stock_entry(source_name)
	return _insert_and_contract(doc, "Stock Entry")


def material_request_to_in_transit_stock_entry(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	from erpnext.stock.doctype.material_request.material_request import make_in_transit_stock_entry

	in_transit_warehouse = (payload.get("in_transit_warehouse") or "").strip()
	if not in_transit_warehouse:
		frappe.throw(_("In Transit Warehouse is required for in-transit stock entry"))
	doc = make_in_transit_stock_entry(source_name, in_transit_warehouse)
	return _insert_and_contract(doc, "Stock Entry")


def material_request_to_work_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import raise_work_orders

	mr = frappe.get_doc("Material Request", source_name)
	if getattr(raise_work_orders, "__code__", None) and raise_work_orders.__code__.co_argcount >= 2:
		work_orders = raise_work_orders(source_name, mr.company)
	else:
		work_orders = raise_work_orders(source_name)
	if not work_orders:
		frappe.throw(_("No Work Order was created from Material Request {0}").format(source_name))
	name = work_orders[0] if isinstance(work_orders, list) else work_orders
	return _doc_contract("Work Order", name)


def material_request_to_pick_list(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import create_pick_list

	doc = create_pick_list(source_name)
	return _insert_and_contract(doc, "Pick List")


def create_subcontracting_receipt_from_asn(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	asn = frappe.get_doc("ASN", source_name)
	order_name = (payload.get("subcontracting_order") or "").strip() or (
		getattr(asn, "subcontracting_order", "") or ""
	).strip()
	if not order_name:
		frappe.throw(
			_(
				"ASN -> Subcontracting Receipt requires subcontracting order context. "
				"Provide subcontracting_order in payload or on ASN."
			)
		)

	from asn_module.handlers.subcontracting import create_receipt_from_subcontracting_order

	return create_receipt_from_subcontracting_order(
		source_doctype="Subcontracting Order",
		source_name=order_name,
		payload=payload,
	)


def _insert_and_contract(doc: Any, fallback_doctype: str) -> dict:
	if isinstance(doc, str):
		return _doc_contract(fallback_doctype, doc)
	is_new_attr = getattr(doc, "is_new", None)
	if callable(is_new_attr):
		needs_insert = bool(is_new_attr())
	elif isinstance(is_new_attr, bool):
		needs_insert = is_new_attr
	else:
		needs_insert = not getattr(doc, "name", None)
	if needs_insert:
		doc.insert(ignore_permissions=True)
	return _doc_contract(getattr(doc, "doctype", fallback_doctype), doc.name)


def _doc_contract(doctype: str, name: str) -> dict:
	route = frappe.scrub(doctype)
	return {
		"doctype": doctype,
		"name": name,
		"url": f"/app/{route}/{name}",
		"message": _("{0} {1} created").format(doctype, name),
	}
