import json

import frappe
from frappe.utils import flt

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
)
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.fetch import fetch_cap_context
from asn_module.stock_cap.messages import may_see_stock_figures
from asn_module.stock_cap.models import Breach
from asn_module.utils.permissions import get_accessible_doc


def breaches_for_asn_rows(
	rows: list[dict],
	exclude_asn_name: str | None = None,
	consumed: dict[tuple[str, str], float] | None = None,
) -> tuple[list[Breach], dict[tuple[str, str], float]]:
	"""Evaluate one ASN's (or one bulk-upload invoice group's) rows against the cap.

	Returns ``(breaches, accepted)``. ``accepted`` is evaluate()'s own record of which
	(branch, item_code) incoming quantities it actually counted -- callers that need to
	carry headroom forward across several calls (the bulk upload loop) must feed this
	dict back in as the next call's ``consumed`` rather than re-deriving it themselves, so
	the cap-warehouse / cap-is-set / positive-qty filters live in exactly one place.
	"""
	lines = collect_lines_from_asn_rows(rows)
	if not lines:
		return [], {}

	context = fetch_cap_context(lines, exclude_asn_name=exclude_asn_name)
	return evaluate(lines, context, consumed=consumed)


def breaches_for_asn_doc(doc) -> list[Breach]:
	breaches, _accepted = breaches_for_asn_rows(asn_rows_from_doc(doc), exclude_asn_name=doc.name or None)
	return breaches


def breaches_for_purchase_receipt(doc) -> list[Breach]:
	"""Exclude the Purchase Order Items this receipt is itself receiving.

	Excludes by ``purchase_order_item`` rather than by the receipt's ``asn`` field: ``asn``
	is set only when the receipt was created through the ASN's own "Create Purchase
	Receipt" action (handlers/purchase_receipt.py:create_from_asn). Nothing stops the
	standard Purchase Order -> Create -> Purchase Receipt action, which leaves ``asn``
	empty, and that receipt's goods must still not be counted once as in-transit on the
	originating ASN and again as this receipt's own incoming. Excluding by PO item also
	keeps ASN Items this receipt does *not* cover -- a sibling item on the same ASN, or a
	still-unreceived remainder after a partial receipt -- correctly counted as in-transit,
	unlike excluding the whole ASN would.
	"""
	lines = collect_lines_from_purchase_receipt(doc)
	if not lines:
		return []

	exclude_po_items = {row.purchase_order_item for row in (doc.items or []) if row.purchase_order_item}
	context = fetch_cap_context(lines, exclude_po_items=exclude_po_items)
	breaches, _accepted = evaluate(lines, context)
	return breaches


@frappe.whitelist()
def get_stock_cap_preview(items, asn_name: str | None = None) -> list[dict]:
	"""Headroom preview for the ASN entry form.

	Suppliers receive allowed_qty and a breach flag only; stock figures are withheld
	unless the caller can read Item.
	"""
	if isinstance(items, str):
		items = json.loads(items)

	rows = []
	for index, item in enumerate(items or [], start=1):
		purchase_order = (item.get("purchase_order") or "").strip()
		if not purchase_order:
			continue

		get_accessible_doc("Purchase Order", purchase_order)
		rows.append(
			{
				"idx": item.get("idx") or index,
				"purchase_order": purchase_order,
				"purchase_order_item": item.get("purchase_order_item"),
				"item_code": item.get("item_code"),
				"qty": flt(item.get("qty")),
			}
		)

	detailed = may_see_stock_figures()
	breaches, _accepted = breaches_for_asn_rows(rows, exclude_asn_name=asn_name)
	preview = []
	for breach in breaches:
		entry = {
			"item_code": breach.item_code,
			"row_idxs": list(breach.row_idxs),
			"breached": True,
			"allowed_qty": flt(breach.allowed_qty),
		}
		if detailed:
			entry.update(
				{
					"branch": breach.branch,
					"on_hand": flt(breach.on_hand),
					"in_transit": flt(breach.in_transit),
					"projected": flt(breach.projected),
					"cap": flt(breach.cap),
				}
			)
		preview.append(entry)

	return preview
