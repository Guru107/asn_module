from __future__ import annotations

import inspect
from typing import Any

import frappe
from frappe import _


def material_request_to_purchase_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order

	supplier = _resolve_supplier_for_material_request(source_name, payload)

	doc = make_purchase_order(source_name)
	if supplier and not (getattr(doc, "supplier", "") or "").strip():
		doc.supplier = supplier
		set_missing_values = getattr(doc, "set_missing_values", None)
		if callable(set_missing_values):
			set_missing_values()
	if not (getattr(doc, "supplier", "") or "").strip():
		frappe.throw(
			_(
				"Supplier is required to create Purchase Order from Material Request {0}. "
				"Provide supplier in payload or configure Item Default supplier."
			).format(source_name)
		)
	return _insert_and_contract(doc, "Purchase Order")


def material_request_to_rfq(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	from erpnext.stock.doctype.material_request.material_request import make_request_for_quotation

	supplier = _resolve_supplier_for_material_request(source_name, payload)
	doc = make_request_for_quotation(source_name)
	if supplier:
		existing_suppliers = {
			(str(getattr(row, "supplier", "") or "")).strip() for row in list(getattr(doc, "suppliers", []) or [])
		}
		if supplier not in existing_suppliers and hasattr(doc, "append"):
			doc.append("suppliers", {"supplier": supplier})
	if not list(getattr(doc, "suppliers", []) or []):
		frappe.throw(
			_(
				"Supplier is required to create Request for Quotation from Material Request {0}. "
				"Provide supplier in payload or configure Item Default supplier."
			).format(source_name)
		)
	return _insert_and_contract(doc, "Request for Quotation")


def material_request_to_supplier_quotation(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	from erpnext.stock.doctype.material_request.material_request import make_supplier_quotation

	supplier = _resolve_supplier_for_material_request(source_name, payload)
	doc = make_supplier_quotation(source_name)
	if supplier and not (getattr(doc, "supplier", "") or "").strip():
		doc.supplier = supplier
	if not (getattr(doc, "supplier", "") or "").strip():
		frappe.throw(
			_(
				"Supplier is required to create Supplier Quotation from Material Request {0}. "
				"Provide supplier in payload or configure Item Default supplier."
			).format(source_name)
		)
	return _insert_and_contract(doc, "Supplier Quotation")


def material_request_to_stock_entry(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import make_stock_entry

	doc = make_stock_entry(source_name)
	return _insert_and_contract(doc, "Stock Entry")


def material_request_to_in_transit_stock_entry(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype
	from erpnext.stock.doctype.material_request.material_request import make_in_transit_stock_entry

	mr = frappe.get_doc("Material Request", source_name)
	in_transit_warehouse = (payload.get("in_transit_warehouse") or "").strip()
	if not in_transit_warehouse:
		in_transit_warehouse = (
			frappe.db.get_value("Company", mr.company, "default_in_transit_warehouse") or ""
		).strip()
	if not in_transit_warehouse:
		in_transit_warehouse = (
			frappe.db.get_value(
				"Warehouse",
				{"company": mr.company, "warehouse_type": "Transit"},
				"name",
			)
			or ""
		).strip()
	if not in_transit_warehouse:
		frappe.throw(_("In Transit Warehouse is required for in-transit stock entry"))
	doc = make_in_transit_stock_entry(source_name, in_transit_warehouse)
	return _insert_and_contract(doc, "Stock Entry")


def material_request_to_work_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	del source_doctype, payload
	from erpnext.stock.doctype.material_request.material_request import raise_work_orders

	mr = frappe.get_doc("Material Request", source_name)
	if _function_accepts_two_or_more_args(raise_work_orders):
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
		order_name = _resolve_subcontracting_order_from_asn(asn)
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


def _resolve_subcontracting_order_from_asn(asn: Any) -> str:
	purchase_orders = sorted(
		{
			(str(getattr(item, "purchase_order", "") or "")).strip()
			for item in list(getattr(asn, "items", []) or [])
			if (str(getattr(item, "purchase_order", "") or "")).strip()
		}
	)
	if not purchase_orders:
		return ""

	rows = frappe.get_all(
		"Subcontracting Order",
		filters={
			"purchase_order": ["in", purchase_orders],
			"docstatus": 1,
		},
		fields=["name"],
		order_by="modified desc",
		limit_page_length=1,
	)
	if not rows:
		return ""
	return str(rows[0].get("name") or "").strip()


def _resolve_material_request_supplier(material_request: str) -> str:
	mr = frappe.get_doc("Material Request", material_request)
	item_codes = sorted(
		{
			(str(getattr(item, "item_code", "") or "")).strip()
			for item in list(getattr(mr, "items", []) or [])
			if (str(getattr(item, "item_code", "") or "")).strip()
		}
	)
	if not item_codes:
		return ""

	suppliers = set()
	for item_code in item_codes:
		supplier = (
			frappe.db.get_value(
				"Item Default",
				{
					"parent": item_code,
					"parenttype": "Item",
					"company": mr.company,
				},
				"default_supplier",
			)
			or frappe.db.get_value("Item Supplier", {"parent": item_code}, "supplier")
			or ""
		).strip()
		if supplier:
			suppliers.add(supplier)

	if len(suppliers) > 1:
		frappe.throw(
			_(
				"Material Request {0} resolves to multiple suppliers ({1}). "
				"Provide supplier in payload."
			).format(material_request, ", ".join(sorted(suppliers)))
		)

	return next(iter(suppliers), "")


def _resolve_supplier_for_material_request(material_request: str, payload: dict) -> str:
	return (payload.get("supplier") or "").strip() or _resolve_material_request_supplier(material_request)


def _function_accepts_two_or_more_args(fn: Any) -> bool:
	try:
		return len(inspect.signature(fn).parameters) >= 2
	except (TypeError, ValueError):
		return False


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
