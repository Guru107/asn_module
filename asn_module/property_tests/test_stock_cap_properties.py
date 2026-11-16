from hypothesis import given
from hypothesis import strategies as st

from asn_module.property_tests import settings  # loads HYPOTHESIS_PROFILE
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import CapContext, Line
from asn_module.stock_cap.precision import flt_qty
from asn_module.tests.compat import IntegrationTestCase

BRANCH = "B"
ITEM = "I"
WH = "W"

quantities = st.floats(min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False)
caps = st.floats(min_value=0.01, max_value=10_000, allow_nan=False, allow_infinity=False)
# Purchase Order Item conversion_factor: stock units per purchase unit, either side of 1.
factors = st.floats(min_value=0.001, max_value=1_000, allow_nan=False, allow_infinity=False)


def _context(cap: float, on_hand: float, in_transit: float) -> CapContext:
	return CapContext(
		cap_warehouses={BRANCH: frozenset({WH})},
		max_stock={(BRANCH, ITEM): cap},
		on_hand={(BRANCH, ITEM): on_hand},
		in_transit={(BRANCH, ITEM): in_transit},
	)


def _line(qty: float, factor: float = 1.0, row_idx: int = 1) -> Line:
	return Line(
		branch=BRANCH, item_code=ITEM, warehouse=WH, stock_qty=qty, row_idx=row_idx, conversion_factor=factor
	)


class TestStockCapProperties(IntegrationTestCase):
	@given(caps, quantities, quantities, quantities, quantities)
	def test_projected_is_monotonic_in_declared_quantity(self, cap, on_hand, in_transit, qty, extra):
		context = _context(cap, on_hand, in_transit)
		low, _accepted = evaluate([_line(qty)], context)
		high, _accepted = evaluate([_line(qty + extra)], context)
		if low:
			self.assertTrue(high, "a larger quantity must not turn a breach into a pass")
			self.assertLessEqual(low[0].projected, high[0].projected)

	@given(caps, quantities, quantities, quantities)
	def test_breach_holds_exactly_when_projected_exceeds_cap(self, cap, on_hand, in_transit, qty):
		breaches, _accepted = evaluate([_line(qty)], _context(cap, on_hand, in_transit))
		projected = flt_qty(on_hand + in_transit + qty)
		self.assertEqual(bool(breaches), qty > 0 and projected > flt_qty(cap))

	@given(caps, quantities, quantities, quantities)
	def test_allowed_qty_is_the_largest_non_breaching_quantity(self, cap, on_hand, in_transit, qty):
		context = _context(cap, on_hand, in_transit)
		breaches, _accepted = evaluate([_line(qty)], context)
		if not breaches:
			return

		no_breaches, _accepted = evaluate([_line(breaches[0].allowed_qty)], context)
		self.assertEqual(no_breaches, [])

	@given(caps, quantities, quantities, quantities, factors)
	def test_allowed_purchase_qty_times_factor_never_breaches(
		self, cap, on_hand, in_transit, purchase_qty, factor
	):
		context = _context(cap, on_hand, in_transit)
		breaches, _accepted = evaluate([_line(purchase_qty * factor, factor)], context)
		if not breaches:
			return

		# Submit multiplies the typed purchase qty by the same raw factor (collect.py).
		retyped = breaches[0].allowed_purchase_qty * factor
		no_breaches, _accepted = evaluate([_line(retyped, factor)], context)
		self.assertEqual(no_breaches, [])

	@given(caps, quantities, quantities, st.lists(st.tuples(quantities, factors), min_size=2, max_size=5))
	def test_lines_of_one_item_are_capped_as_one_group(self, cap, on_hand, in_transit, rows):
		lines = [_line(qty * factor, factor, idx) for idx, (qty, factor) in enumerate(rows, start=1)]
		breaches, _accepted = evaluate(lines, _context(cap, on_hand, in_transit))

		counted = [line for line in lines if line.stock_qty > 0]
		incoming = sum(line.stock_qty for line in counted)
		self.assertEqual(
			bool(breaches), bool(counted) and flt_qty(on_hand + in_transit + incoming) > flt_qty(cap)
		)
		if not breaches:
			return

		breach = breaches[0]
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breach.row_idxs, tuple(line.row_idx for line in counted))
		if len({line.conversion_factor for line in counted}) > 1:
			# No single purchase UOM to offer: the figure falls back to stock units.
			self.assertEqual(breach.allowed_purchase_qty, breach.allowed_qty)

	@given(caps, quantities, quantities, quantities, quantities)
	def test_consumed_carries_headroom_into_the_next_evaluation(
		self, cap, on_hand, in_transit, first, second
	):
		context = _context(cap, on_hand, in_transit)
		_breaches, accepted = evaluate([_line(first)], context)
		self.assertEqual(accepted, {(BRANCH, ITEM): first} if first > 0 else {})

		breaches, _accepted = evaluate([_line(second)], context, consumed=accepted)
		carried = accepted.get((BRANCH, ITEM), 0.0)
		projected = flt_qty(on_hand + in_transit + carried + second)
		self.assertEqual(bool(breaches), second > 0 and projected > flt_qty(cap))
		if not breaches:
			return

		no_breaches, _accepted = evaluate([_line(breaches[0].allowed_qty)], context, consumed=accepted)
		self.assertEqual(no_breaches, [])
