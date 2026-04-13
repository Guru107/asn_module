from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from asn_module.asn_module.doctype.asn.asn import _get_shipped_qty_by_po_item
from asn_module.templates.pages.asn import _get_supplier_for_user, get_open_purchase_orders_for_supplier


def _get_supplier() -> str:
	supplier = _get_supplier_for_user(frappe.session.user)
	if supplier:
		return supplier
	frappe.throw(_("Only supplier portal users can access ASN create search."), frappe.PermissionError)


@frappe.whitelist()
def search_open_purchase_orders(txt: str = "", start: int = 0, page_len: int = 20) -> list[dict]:
	supplier = _get_supplier()
	txt = (txt or "").strip().lower()
	entries = get_open_purchase_orders_for_supplier(supplier)
	filtered = [
		{"value": po.name, "description": f"{po.status} | {po.transaction_date}"}
		for po in entries
		if not txt or txt in po.name.lower()
	]
	return filtered[start : start + page_len]


@frappe.whitelist()
def search_purchase_order_items(
	purchase_order: str,
	txt: str = "",
	start: int = 0,
	page_len: int = 20,
) -> list[dict]:
	supplier = _get_supplier()
	open_po_names = {po.name for po in get_open_purchase_orders_for_supplier(supplier)}
	purchase_order = (purchase_order or "").strip()
	if purchase_order not in open_po_names:
		frappe.throw(_("Purchase Order is not available for this supplier."), frappe.PermissionError)

	txt = (txt or "").strip().lower()
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=["name", "idx", "item_code", "item_name", "uom", "rate", "qty"],
		limit_page_length=0,
	)
	shipped_qty_by_item = _get_shipped_qty_by_po_item([row.name for row in rows])
	filtered = []
	for row in rows:
		if txt:
			haystack = [
				(row.item_code or "").lower(),
				(row.item_name or "").lower(),
				str(row.idx or "").lower(),
			]
			if not any(txt in value for value in haystack):
				continue
		remaining_qty = flt(row.qty) - flt(shipped_qty_by_item.get(row.name, 0))
		if remaining_qty <= 0:
			continue
		filtered.append(
			{
				"value": row.item_code,
				"item_name": row.item_name,
				"sr_no": str(row.idx),
				"uom": row.uom,
				"rate": row.rate,
				"remaining_qty": remaining_qty,
				"purchase_order_item": row.name,
			}
		)

	return filtered[start : start + page_len]
