from dataclasses import dataclass

from asn_module.stock_cap.precision import floor_qty


@dataclass(frozen=True)
class Line:
	"""One quantity landing in one warehouse, already converted to stock UOM."""

	branch: str
	item_code: str
	warehouse: str
	stock_qty: float
	row_idx: int
	conversion_factor: float = 1.0


@dataclass(frozen=True)
class CapContext:
	"""Everything the evaluator needs, as plain data. Built by fetch_cap_context.

	``max_stock`` is keyed by (branch, item_code): the same item may carry a different
	ceiling in each branch. ``on_hand`` and ``in_transit`` share that key because stock is
	pooled across the branch's cap warehouses.
	"""

	cap_warehouses: dict[str, frozenset[str]]
	max_stock: dict[tuple[str, str], float]
	on_hand: dict[tuple[str, str], float]
	in_transit: dict[tuple[str, str], float]


@dataclass(frozen=True)
class Breach:
	"""``baseline`` is everything counted against the cap except this document's own incoming
	quantity: ``on_hand + in_transit + consumed``, exactly as evaluate() computes the non-incoming
	part of ``projected``. It is stored rather than derived (e.g. via ``projected - incoming``)
	because that round-trip loses precision: floating-point addition can absorb a tiny on_hand/
	in_transit/consumed residual into a much larger incoming quantity, and subtracting incoming
	back out afterwards does not recover it. See ``allowed_qty`` below.
	"""

	branch: str
	item_code: str
	row_idxs: tuple[int, ...]
	on_hand: float
	in_transit: float
	baseline: float
	incoming: float
	projected: float
	cap: float
	conversion_factor: float = 1.0

	@property
	def allowed_qty(self) -> float:
		"""Largest additional quantity that would not breach. The only figure suppliers may see.

		Declare exactly this quantity and it will not be refused, so it must be computed from the
		exact inputs, not re-derived from a lossy expression. It is ``cap - baseline``, using the
		``baseline`` evaluate() already had on hand -- never ``projected - incoming``, which
		round-trips through addition and back and can silently lose a residual smaller than the
		incoming quantity that absorbed it, certifying a figure that then breaches on re-evaluation.

		Rounded down to the Float precision from System Settings. Rounding up, the way
		``flt`` stores a field, can certify a quantity that the same precision then refuses.
		"""
		headroom = max(self.cap - self.baseline, 0.0)
		return floor_qty(headroom)

	@property
	def allowed_purchase_qty(self) -> float:
		"""``allowed_qty`` in the purchase UOM suppliers type.

		``conversion_factor`` is stock units per purchase unit. A mixed-factor group sets it
		to 0, and this falls back to stock units so the figure is not a false purchase qty.
		"""
		factor = self.conversion_factor if self.conversion_factor > 0 else 1.0
		headroom = max(self.cap - self.baseline, 0.0)
		return floor_qty(headroom / factor)
