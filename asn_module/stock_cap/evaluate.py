from asn_module.stock_cap.models import Breach, CapContext, Line


def _as_float(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def evaluate(
	lines: list[Line],
	context: CapContext,
	consumed: dict[tuple[str, str], float] | None = None,
) -> tuple[list[Breach], dict[tuple[str, str], float]]:
	"""Decide which (branch, item) groups exceed their maximum.

	Pure: no database access and no frappe imports, so the whole branch matrix is
	testable without stock ledger fixtures. Every skip here is a documented
	fail-open rule from the spec.

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
		if _as_float(context.max_stock.get(line.item_code)) <= 0:
			continue

		grouped.setdefault((line.branch, line.item_code), []).append(line)

	breaches = []
	accepted: dict[tuple[str, str], float] = {}
	for (branch, item_code), group in grouped.items():
		cap = _as_float(context.max_stock.get(item_code))
		on_hand = _as_float(context.on_hand.get((branch, item_code)))
		in_transit = _as_float(context.in_transit.get((branch, item_code)))
		incoming = sum(_as_float(line.stock_qty) for line in group)
		accepted[(branch, item_code)] = incoming
		projected = on_hand + in_transit + incoming + _as_float(consumed.get((branch, item_code)))

		if projected <= cap:
			continue

		breaches.append(
			Breach(
				branch=branch,
				item_code=item_code,
				row_idxs=tuple(sorted(line.row_idx for line in group)),
				on_hand=on_hand,
				in_transit=in_transit,
				incoming=incoming,
				projected=projected,
				cap=cap,
			)
		)

	return sorted(breaches, key=lambda breach: (breach.branch, breach.item_code)), accepted
