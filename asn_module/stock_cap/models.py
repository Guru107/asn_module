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
	"""Everything the evaluator needs, as plain data. Built by fetch_cap_context."""

	cap_warehouses: dict[str, frozenset[str]]
	max_stock: dict[str, float]
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
		"""Largest additional quantity that would not breach. The only figure suppliers may see."""
		return max(self.cap - (self.projected - self.incoming), 0.0)
