import frappe
from frappe import _

from asn_module.stock_cap.models import Breach
from asn_module.stock_cap.precision import flt_qty


def may_see_stock_figures() -> bool:
	"""Only users who can read Item may see on-hand, in-transit, and maximum figures.

	Supplier portal users cannot, so their messages carry Allowed Qty alone.
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


def _redacted(breach: Breach) -> str:
	"""The figure is the total this document may declare, not an amount to add on top.

	When the lines share one conversion factor it is in the purchase UOM the supplier types.
	A mixed-factor group has no single purchase quantity, so the message says stock UOM.
	"""
	rows = ", ".join(str(idx) for idx in breach.row_idxs)
	if breach.conversion_factor > 0:
		return _("Item {0} (rows {1}): you may declare at most {2}.").format(
			breach.item_code,
			rows,
			flt_qty(breach.allowed_purchase_qty),
		)
	return _("Item {0} (rows {1}): you may declare at most {2} in stock UOM.").format(
		breach.item_code,
		rows,
		flt_qty(breach.allowed_qty),
	)


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
