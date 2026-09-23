from asn_module.stock_cap.models import Breach, CapContext, Line
from asn_module.stock_cap.precision import flt_qty


def _as_float(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _group_conversion_factor(group: list[Line]) -> float:
	"""Purchase-to-stock factor when every line in the group shares one. Otherwise 0."""
	factors = set()
	for line in group:
		factor = _as_float(getattr(line, "conversion_factor", 1) or 1)
		if factor <= 0:
			factor = 1.0
		factors.add(flt_qty(factor))
	if len(factors) == 1:
		return factors.pop()
	return 0.0


def evaluate(
	lines: list[Line],
	context: CapContext,
	consumed: dict[tuple[str, str], float] | None = None,
) -> tuple[list[Breach], dict[tuple[str, str], float]]:
	"""Decide which (branch, item) groups exceed their maximum.

	Every skip here is a documented fail-open rule from the spec. Quantities are compared
	at the Float precision Frappe uses for fields that do not set their own, so a binary
	sum such as 1.1 + 2.2 still counts as the cap 3.3.

	Returns ``(breaches, accepted)``. ``accepted`` is the incoming quantity, keyed by
	(branch, item_code), for every group that survived the same filters used to decide
	breaches -- the cap-warehouse membership test, the cap-is-set test, and the
	non-positive-qty filter -- regardless of whether that group itself breached. Callers
	that carry headroom forward across several evaluations (the bulk upload loop) must
	reuse this dict rather than re-deriving it, so the filter rule lives in exactly one
	place. A caller that only wants a breach-free group's contribution should check
	``breaches`` itself before folding ``accepted`` in.
	"""
	consumed = consumed or {}
	grouped: dict[tuple[str, str], list[Line]] = {}

	for line in lines:
		if _as_float(line.stock_qty) <= 0:
			continue
		cap_warehouses = context.cap_warehouses.get(line.branch)
		if not cap_warehouses or line.warehouse not in cap_warehouses:
			continue
		if _as_float(context.max_stock.get((line.branch, line.item_code))) <= 0:
			continue

		grouped.setdefault((line.branch, line.item_code), []).append(line)

	breaches = []
	accepted: dict[tuple[str, str], float] = {}
	for (branch, item_code), group in grouped.items():
		cap = _as_float(context.max_stock.get((branch, item_code)))
		on_hand = _as_float(context.on_hand.get((branch, item_code)))
		in_transit = _as_float(context.in_transit.get((branch, item_code)))
		incoming = sum(_as_float(line.stock_qty) for line in group)
		accepted[(branch, item_code)] = incoming
		# Everything counted against the cap except this document's own incoming qty.
		# Stored on the Breach as `baseline` so allowed_qty can use it directly instead
		# of re-deriving it by subtracting incoming back out of projected.
		baseline = on_hand + in_transit + _as_float(consumed.get((branch, item_code)))
		projected = baseline + incoming

		if flt_qty(projected) <= flt_qty(cap):
			continue

		breaches.append(
			Breach(
				branch=branch,
				item_code=item_code,
				row_idxs=tuple(sorted(line.row_idx for line in group)),
				on_hand=on_hand,
				in_transit=in_transit,
				baseline=baseline,
				incoming=incoming,
				projected=projected,
				cap=cap,
				conversion_factor=_group_conversion_factor(group),
			)
		)

	return sorted(breaches, key=lambda breach: (breach.branch, breach.item_code)), accepted
