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


# The portal dropdowns ask for 200; a client may not ask for more.
MAX_PAGE_LEN = 200


def _normalize_paging(start: int | str, page_len: int | str) -> tuple[int, int]:
	try:
		start_int = max(int(start), 0)
	except (TypeError, ValueError):
		start_int = 0
	try:
		page_len_int = min(max(int(page_len), 1), MAX_PAGE_LEN)
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


def _unit_price_po_item_names(purchase_order: str) -> set[str]:
	"""PO Item names on a unit-price order (ordered qty zero on the line)."""
	if not purchase_order or not frappe.db.has_column("Purchase Order", "has_unit_price_items"):
		return set()
	if not cint(frappe.db.get_value("Purchase Order", purchase_order, "has_unit_price_items")):
		return set()
	return {
		row["name"]
		for row in frappe.get_all(
			"Purchase Order Item",
			filters={"parent": purchase_order},
			fields=["name", "qty"],
			limit_page_length=0,
		)
		if flt(row.get("qty")) == 0
	}


@frappe.whitelist(methods=["GET"])
def search_open_purchase_orders(txt: str = "", start: int = 0, page_len: int = 20) -> list[dict]:
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
	entries = get_open_purchase_orders_for_supplier(
		supplier, txt=(txt or "").strip(), start=start, page_len=page_len
	)
	return [{"value": po.name, "description": f"{po.status} | {po.transaction_date}"} for po in entries]


@frappe.whitelist(methods=["GET"])
def search_open_subcontracting_orders(txt: str = "", start: int = 0, page_len: int = 20) -> list[dict]:
	supplier = _get_supplier()
	start, page_len = _normalize_paging(start, page_len)
	entries = get_open_subcontracting_orders_for_supplier(
		supplier, txt=(txt or "").strip(), start=start, page_len=page_len
	)
	return [{"value": row.name, "description": f"{row.status} | {row.transaction_date}"} for row in entries]


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


@frappe.whitelist(methods=["GET"])
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
	if not get_open_subcontracting_orders_for_supplier(supplier, names=[order_name], page_len=1):
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


@frappe.whitelist(methods=["GET"])
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
	purchase_order = (purchase_order or "").strip()
	if not get_open_purchase_orders_for_supplier(supplier, names=[purchase_order], page_len=1):
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
	unit_price_items = _unit_price_po_item_names(purchase_order)
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
			if row_name not in unit_price_items:
				continue
			remaining_qty = 0
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
