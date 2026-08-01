import json

import frappe
from frappe import _
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


def breaches_for_asn_rows(
	rows: list[dict],
	exclude_asn_name: str | None = None,
	consumed: dict[tuple[str, str], float] | None = None,
) -> list[Breach]:
	lines = collect_lines_from_asn_rows(rows)
	if not lines:
		return []

	context = fetch_cap_context(lines, exclude_asn_name=exclude_asn_name)
	return evaluate(lines, context, consumed=consumed)


def breaches_for_asn_doc(doc) -> list[Breach]:
	return breaches_for_asn_rows(asn_rows_from_doc(doc), exclude_asn_name=doc.name or None)


def breaches_for_purchase_receipt(doc) -> list[Breach]:
	"""Exclude the ASN this receipt came from.

	At before_submit that ASN is still Submitted with received_qty 0, so its quantity
	would otherwise be counted once as in-transit and again as this receipt's own.
	"""
	lines = collect_lines_from_purchase_receipt(doc)
	if not lines:
		return []

	context = fetch_cap_context(lines, exclude_asn_name=getattr(doc, "asn", None) or None)
	return evaluate(lines, context)


def consumed_from_breach_free_rows(rows: list[dict]) -> dict[tuple[str, str], float]:
	"""Headroom claimed by rows already accepted earlier in the same bulk upload."""
	consumed: dict[tuple[str, str], float] = {}
	for line in collect_lines_from_asn_rows(rows):
		key = (line.branch, line.item_code)
		consumed[key] = consumed.get(key, 0.0) + flt(line.stock_qty)

	return consumed


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

		_assert_purchase_order_access(purchase_order)
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
	preview = []
	for breach in breaches_for_asn_rows(rows, exclude_asn_name=asn_name):
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


def _assert_purchase_order_access(purchase_order: str):
	doc = frappe.get_doc("Purchase Order", purchase_order)
	if doc.has_permission("read") or frappe.has_website_permission(doc, "read", user=frappe.session.user):
		return

	frappe.throw(
		_("Not permitted to access Purchase Order {0}").format(purchase_order),
		frappe.PermissionError,
	)
