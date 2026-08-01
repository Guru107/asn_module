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
) -> list[Breach]:
	"""Decide which (branch, item) groups exceed their maximum.

	Pure: no database access and no frappe imports, so the whole branch matrix is
	testable without stock ledger fixtures. Every skip here is a documented
	fail-open rule from the spec.
	"""
	consumed = consumed or {}
	grouped: dict[tuple[str, str], list[Line]] = {}

	for line in lines:
		cap_warehouses = context.cap_warehouses.get(line.branch)
		if not cap_warehouses or line.warehouse not in cap_warehouses:
			continue
		if _as_float(context.max_stock.get(line.item_code)) <= 0:
			continue

		grouped.setdefault((line.branch, line.item_code), []).append(line)

	breaches = []
	for (branch, item_code), group in grouped.items():
		cap = _as_float(context.max_stock.get(item_code))
		on_hand = _as_float(context.on_hand.get((branch, item_code)))
		in_transit = _as_float(context.in_transit.get((branch, item_code)))
		incoming = sum(_as_float(line.stock_qty) for line in group)
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

	return sorted(breaches, key=lambda breach: (breach.branch, breach.item_code))
