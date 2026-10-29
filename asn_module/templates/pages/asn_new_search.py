"""Supplier portal search whitelists for ASN create.

Line-level reads use ``frappe.get_all`` (same as ``asn.py`` / ``asn_new.py``): portal roles
have no read permission on PO Item, SCO Item, ASN Item, or ASN. Each endpoint scopes by
supplier and open order checks before reading; ``get_list`` without bypass would return
nothing, and ``get_list(ignore_permissions=True)`` is equivalent to ``get_all``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from asn_module.asn_module.doctype.asn.asn import remaining_qty_by_purchase_order_item
from asn_module.templates.pages.asn import (
	_get_supplier_for_user,
	get_open_purchase_orders_for_supplier,
	get_open_subcontracting_orders_for_supplier,
)


def _normalize_paging(start: int | str, page_len: int | str) -> tuple[int, int]:
	try:
		start_int = max(int(start), 0)
	except (TypeError, ValueError):
		start_int = 0
	try:
		page_len_int = max(int(page_len), 1)
	except (TypeError, ValueError):
		page_len_int = 20
	return start_int, page_len_int


def _get_supplier() -> str:
	supplier = _get_supplier_for_user(frappe.session.user)
	if supplier:
		return supplier
	frappe.throw(_("Only supplier portal users can access ASN create search."), frappe.PermissionError)


def supplier_draft_asn_name(supplier: str | None, asn_name: str | None) -> str | None:
	"""The ASN to leave out of Remaining Qty: this supplier's own unsubmitted draft."""
	name = (asn_name or "").strip()
	if not supplier or not name:
		return None
	row = frappe.db.get_value("ASN", name, ["supplier", "docstatus"], as_dict=True)
	if not row or row.supplier != supplier or cint(row.docstatus) != 0:
		return None
	return name


@frappe.whitelist()
def search_open_purchase_orders(txt: str = "", start: int = 0, page_len: int = 20) -> list[dict]:
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
	txt = (txt or "").strip().lower()
	entries = get_open_purchase_orders_for_supplier(supplier)
	filtered = [
		{"value": po.name, "description": f"{po.status} | {po.transaction_date}"}
		for po in entries
		if not txt or txt in po.name.lower()
	]
	return filtered[start : start + page_len]


@frappe.whitelist()
def search_open_subcontracting_orders(txt: str = "", start: int = 0, page_len: int = 20) -> list[dict]:
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
	txt = (txt or "").strip().lower()
	entries = get_open_subcontracting_orders_for_supplier(supplier)
	filtered = [
		{"value": row.name, "description": f"{row.status} | {row.transaction_date}"}
		for row in entries
		if not txt or txt in row.name.lower()
	]
	return filtered[start : start + page_len]


def _unreceived_qty_by_subcontracting_order_item(
	line_names: list[str], exclude_asn_name: str | None = None
) -> dict[str, float]:
	"""Shipped Qty not yet received on ASNs that are not Cancelled or Closed."""
	if not line_names:
		return {}
	asn_rows = frappe.get_all(
		"ASN Item",
		filters={"subcontracting_order_item": ["in", line_names]},
		fields=["subcontracting_order_item", "qty", "received_qty", "parent"],
		limit_page_length=0,
	)
	parents = {row["parent"] for row in asn_rows if row.get("parent")}
	asn_by_name = {}
	if parents:
		for asn in frappe.get_all(
			"ASN",
			filters={"name": ["in", list(parents)]},
			fields=["name", "docstatus", "status"],
			limit_page_length=0,
		):
			asn_by_name[asn["name"]] = asn
	totals: dict[str, float] = {}
	for row in asn_rows:
		asn = asn_by_name.get(row["parent"])
		if not asn or cint(asn["docstatus"]) == 2 or asn["status"] == "Closed":
			continue
		if exclude_asn_name and row["parent"] == exclude_asn_name:
			continue
		pending = max(flt(row["qty"]) - flt(row["received_qty"]), 0)
		totals[row["subcontracting_order_item"]] = totals.get(row["subcontracting_order_item"], 0) + pending
	return totals


@frappe.whitelist()
def search_subcontracting_order_items(
	subcontracting_order: str,
	txt: str = "",
	start: int = 0,
	page_len: int = 20,
	asn_name: str | None = None,
) -> list[dict]:
	"""Finished goods still open on one of this supplier's Subcontracting Orders.

	Uses ``get_all`` for SCO lines; see module docstring for the supplier-portal read rule.
	"""
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
	order_name = (subcontracting_order or "").strip()
	open_names = {row.name for row in get_open_subcontracting_orders_for_supplier(supplier)}
	if order_name not in open_names:
		frappe.throw(_("Subcontracting Order is not available for this supplier."), frappe.PermissionError)

	txt = (txt or "").strip().lower()
	rows = frappe.get_all(
		"Subcontracting Order Item",
		filters={"parent": order_name},
		fields=["name", "idx", "item_code", "item_name", "stock_uom", "rate", "qty", "received_qty"],
		order_by="idx asc",
		limit_page_length=0,
	)
	shipped = _unreceived_qty_by_subcontracting_order_item(
		[row["name"] for row in rows],
		exclude_asn_name=supplier_draft_asn_name(supplier, asn_name),
	)
	filtered = []
	for row in rows:
		if txt:
			haystack = [
				(row.get("item_code") or "").lower(),
				(row.get("item_name") or "").lower(),
				str(row.get("idx") or "").lower(),
			]
			if not any(txt in value for value in haystack):
				continue
		row_name = row["name"]
		remaining_qty = flt(row["qty"]) - flt(row["received_qty"]) - flt(shipped.get(row_name))
		if remaining_qty < 0:
			remaining_qty = 0
		filtered.append(
			{
				"value": row["item_code"],
				"item_name": row["item_name"],
				"sr_no": str(row["idx"]),
				"uom": row["stock_uom"],
				"rate": row["rate"],
				"remaining_qty": remaining_qty,
				"subcontracting_order": order_name,
				"subcontracting_order_item": row_name,
			}
		)
	return filtered[start : start + page_len]


@frappe.whitelist()
def search_purchase_order_items(
	purchase_order: str,
	txt: str = "",
	start: int = 0,
	page_len: int = 20,
	asn_name: str | None = None,
) -> list[dict]:
	"""PO lines still open for ASN create; uses ``get_all`` — see module docstring."""
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
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
	remaining_by_item = remaining_qty_by_purchase_order_item(
		{row["name"]: flt(row["qty"]) for row in rows},
		exclude_asn_name=supplier_draft_asn_name(supplier, asn_name),
	)
	filtered = []
	for row in rows:
		if txt:
			haystack = [
				(row.get("item_code") or "").lower(),
				(row.get("item_name") or "").lower(),
				str(row.get("idx") or "").lower(),
			]
			if not any(txt in value for value in haystack):
				continue
		row_name = row["name"]
		remaining_qty = remaining_by_item.get(row_name, 0)
		if remaining_qty is not None and remaining_qty <= 0:
			continue
		filtered.append(
			{
				"value": row["item_code"],
				"item_name": row["item_name"],
				"sr_no": str(row["idx"]),
				"uom": row["uom"],
				"rate": row["rate"],
				"remaining_qty": remaining_qty,
				"purchase_order_item": row_name,
			}
		)

	return filtered[start : start + page_len]
