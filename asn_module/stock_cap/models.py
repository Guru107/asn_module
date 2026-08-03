import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
	"""One quantity landing in one warehouse, already converted to stock UOM."""

	branch: str
	item_code: str
	warehouse: str
	stock_qty: float
	row_idx: int


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
	branch: str
	item_code: str
	row_idxs: tuple[int, ...]
	on_hand: float
	in_transit: float
	incoming: float
	projected: float
	cap: float

	@property
	def allowed_qty(self) -> float:
		"""Largest additional quantity that would not breach. The only figure suppliers may see.

		Rounded down to 6 decimal places so the reported figure is never larger than the true
		headroom: floating-point round-trips through ``projected - incoming`` can otherwise land a
		fraction of an ULP above the true headroom, which would make declaring exactly the reported
		quantity breach again.
		"""
		headroom = self.cap - (self.projected - self.incoming)
		if headroom <= 0:
			return 0.0
		return math.floor(headroom * 1_000_000) / 1_000_000
