import frappe
from frappe import _

from asn_module.stock_cap.models import Breach
from asn_module.stock_cap.precision import flt_qty


def may_see_stock_figures() -> bool:
	"""Only users who can read Item may see on-hand, in-transit, and maximum figures.

	Supplier portal users are told, in plain language, that the branch cannot take
	the quantity, and how much they may still declare. On Hand, In Transit Qty, and
	Maximum Stock stay on the desk.
	"""
	return bool(frappe.has_permission("Item", "read"))


def _detailed(breach: Breach) -> str:
	return _(
		"Item {0} in branch {1} (rows {2}): projected stock {3} exceeds maximum {4}. "
		"On hand {5}, in transit {6}, this document {7}."
	).format(
		breach.item_code,
		breach.branch,
		", ".join(str(idx) for idx in breach.row_idxs),
		flt_qty(breach.projected),
		flt_qty(breach.cap),
		flt_qty(breach.on_hand),
		flt_qty(breach.in_transit),
		flt_qty(breach.incoming),
	)


def _qty_text(value) -> str:
	"""A quantity a supplier can read: 20 rather than 20.0, and 0 rather than 0.0."""
	text = format(flt_qty(value), "f").rstrip("0").rstrip(".")
	return text or "0"


def _redacted(breach: Breach) -> str:
	"""Say the branch cannot take the quantity, and how much is still allowed.

	Hide every stock figure. Do not use the internal name Stock Cap.

	When the lines share one conversion factor the quantity is in the purchase UOM the
	supplier types. A mixed-factor group has no single purchase quantity, so that
	quantity is in stock UOM. A full cap has nothing left to declare.
	"""
	rows = ", ".join(str(idx) for idx in breach.row_idxs)
	purchase_uom = breach.conversion_factor > 0
	allowed = breach.allowed_purchase_qty if purchase_uom else breach.allowed_qty
	if flt_qty(allowed) <= 0:
		if purchase_uom:
			return _(
				"Item {0} (rows {1}): the branch already has as much of this item as it can take. "
				"You cannot declare any more."
			).format(breach.item_code, rows)
		return _(
			"Item {0} (rows {1}): the branch already has as much of this item as it can take. "
			"You cannot declare any more in stock UOM."
		).format(breach.item_code, rows)
	if purchase_uom:
		return _(
			"Item {0} (rows {1}): the branch cannot take this quantity. You may declare at most {2}."
		).format(breach.item_code, rows, _qty_text(allowed))
	return _(
		"Item {0} (rows {1}): the branch cannot take this quantity. You may declare at most {2} in stock UOM."
	).format(breach.item_code, rows, _qty_text(allowed))


def format_breaches(breaches: list[Breach], detailed: bool) -> str:
	if not breaches:
		return ""

	formatter = _detailed if detailed else _redacted
	return "\n".join(formatter(breach) for breach in breaches)


def throw_stock_cap_exceeded(breaches: list[Breach]) -> None:
	"""Block submission with the shared "Stock Cap Exceeded" message.

	Both enforcement surfaces (the ASN controller's before_submit hook and the Purchase
	Receipt before_submit hook) need this exact throw, byte-identical message and title
	included -- existing tests assert on both. Callers are expected to have already checked
	``breaches`` is non-empty; ``format_breaches`` degrades to an empty string otherwise,
	which would throw with no message.
	"""
	frappe.throw(
		format_breaches(breaches, detailed=may_see_stock_figures()),
		title=_("Stock Cap Exceeded"),
	)
