import frappe
from frappe.utils import flt

from asn_module.stock_cap.models import Line


def _conversion_factor(value) -> float:
	factor = flt(value)
	return factor if factor > 0 else 1.0


def asn_rows_from_doc(doc) -> list[dict]:
	"""Adapt a saved or unsaved ASN document to the row shape collect_lines_from_asn_rows expects."""
	return [
		{
			"idx": row.idx,
			"purchase_order": row.purchase_order,
			"purchase_order_item": row.purchase_order_item,
			"item_code": row.item_code,
			"qty": flt(row.qty),
		}
		for row in (doc.items or [])
	]


def collect_lines_from_asn_rows(rows: list[dict]) -> list[Line]:
	"""Normalise ASN rows into stock-UOM lines.

	ASN quantities are in the Purchase Order line's purchase UOM, so every quantity is
	multiplied by that line's conversion factor before it can be compared with Bin.
	"""
	usable = [row for row in rows if row.get("purchase_order") and row.get("purchase_order_item")]
	if not usable:
		return []

	# branch is a custom field; without it the cap still applies, resolved from warehouse ownership.
	has_branch = frappe.db.has_column("Purchase Order", "branch")

	purchase_orders = sorted({row["purchase_order"] for row in usable})
	po_rows = frappe.get_all(
		"Purchase Order",
		filters={"name": ["in", purchase_orders]},
		fields=["name", "set_warehouse", *(["branch"] if has_branch else [])],
		limit_page_length=0,
	)
	po_by_name = {row.name: row for row in po_rows}

	po_item_names = sorted({row["purchase_order_item"] for row in usable})
	po_item_rows = frappe.get_all(
		"Purchase Order Item",
		filters={"name": ["in", po_item_names]},
		fields=["name", "item_code", "warehouse", "conversion_factor"],
		limit_page_length=0,
	)
	po_item_by_name = {row.name: row for row in po_item_rows}

	lines = []
	for row in usable:
		purchase_order = po_by_name.get(row["purchase_order"])
		po_item = po_item_by_name.get(row["purchase_order_item"])
		if not purchase_order or not po_item:
			continue

		warehouse = po_item.warehouse or purchase_order.set_warehouse
		if not warehouse:
			continue

		factor = _conversion_factor(po_item.conversion_factor)
		lines.append(
			Line(
				branch=(purchase_order.get("branch") or "") if has_branch else "",
				item_code=po_item.item_code or row["item_code"],
				warehouse=warehouse,
				stock_qty=flt(row["qty"]) * factor,
				row_idx=int(row.get("idx") or 0),
				conversion_factor=factor,
			)
		)

	return lines


def purchase_order_item_receiving_qty(doc) -> dict[str, float]:
	"""Stock-UOM quantity this receipt is actually receiving, keyed by Purchase Order Item.

	Sums the accepted split (``stock_qty``) and the rejected split (``rejected_qty`` x
	``conversion_factor``) for every row against the same Purchase Order Item -- both
	splits reduce the ASN's undelivered quantity for that Purchase Order Item, even
	though the rejected split lands in a different warehouse. Used by
	breaches_for_purchase_receipt to subtract only the quantity this receipt covers from
	in-transit (see fetch.py:_fetch_in_transit), rather than dropping every ASN Item row
	for the Purchase Order Item wholesale.

	Only a receipt linked to an ASN fills that ASN. One with no link may only take
	quantity no open ASN declares, so the ASN stays in transit and nothing comes off.
	"""
	if getattr(doc, "is_return", 0) or not getattr(doc, "asn", None):
		return {}

	receiving: dict[str, float] = {}
	for row in doc.items or []:
		po_item = row.purchase_order_item
		if not po_item:
			continue

		qty = flt(row.stock_qty) + flt(row.rejected_qty) * _conversion_factor(row.conversion_factor)
		if qty > 0:
			receiving[po_item] = receiving.get(po_item, 0.0) + qty

	return receiving


def collect_lines_from_purchase_receipt(doc) -> list[Line]:
	"""Normalise a Purchase Receipt. Its stock_qty is already in stock UOM.

	Returns carry negative quantities and reduce stock, so they can never breach a maximum.
	Rejected quantities post to a separate warehouse and become their own line.
	"""
	if getattr(doc, "is_return", 0):
		return []

	branch = getattr(doc, "branch", None) or ""
	lines = []
	for row in doc.items or []:
		factor = _conversion_factor(row.conversion_factor)
		if flt(row.stock_qty) > 0 and row.warehouse:
			lines.append(
				Line(
					branch=branch,
					item_code=row.item_code,
					warehouse=row.warehouse,
					stock_qty=flt(row.stock_qty),
					row_idx=int(row.idx or 0),
					conversion_factor=factor,
				)
			)

		rejected_stock_qty = flt(row.rejected_qty) * factor
		if rejected_stock_qty > 0 and row.rejected_warehouse:
			lines.append(
				Line(
					branch=branch,
					item_code=row.item_code,
					warehouse=row.rejected_warehouse,
					stock_qty=rejected_stock_qty,
					row_idx=int(row.idx or 0),
					conversion_factor=factor,
				)
			)

	return lines
