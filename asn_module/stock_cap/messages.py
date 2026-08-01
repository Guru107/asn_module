import frappe
from frappe import _
from frappe.utils import flt

from asn_module.stock_cap.models import Breach


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
		flt(breach.projected),
		flt(breach.cap),
		flt(breach.on_hand),
		flt(breach.in_transit),
		flt(breach.incoming),
	)


def _redacted(breach: Breach) -> str:
	return _("Item {0} (rows {1}): you may declare at most {2} more.").format(
		breach.item_code,
		", ".join(str(idx) for idx in breach.row_idxs),
		flt(breach.allowed_qty),
	)


def format_breaches(breaches: list[Breach], detailed: bool) -> str:
	if not breaches:
		return ""

	formatter = _detailed if detailed else _redacted
	return "\n".join(formatter(breach) for breach in breaches)
