from frappe.tests import UnitTestCase
from hypothesis import given
from hypothesis import strategies as st

from asn_module.property_tests import settings  # loads HYPOTHESIS_PROFILE
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import CapContext, Line

BRANCH = "B"
ITEM = "I"
WH = "W"

quantities = st.floats(min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False)
caps = st.floats(min_value=0.01, max_value=10_000, allow_nan=False, allow_infinity=False)


def _context(cap: float, on_hand: float, in_transit: float) -> CapContext:
	return CapContext(
		cap_warehouses={BRANCH: frozenset({WH})},
		max_stock={ITEM: cap},
		on_hand={(BRANCH, ITEM): on_hand},
		in_transit={(BRANCH, ITEM): in_transit},
	)


def _line(qty: float) -> Line:
	return Line(branch=BRANCH, item_code=ITEM, warehouse=WH, stock_qty=qty, row_idx=1)


class TestStockCapProperties(UnitTestCase):
	@given(caps, quantities, quantities, quantities, quantities)
	def test_projected_is_monotonic_in_declared_quantity(self, cap, on_hand, in_transit, qty, extra):
		context = _context(cap, on_hand, in_transit)
		low = evaluate([_line(qty)], context)
		high = evaluate([_line(qty + extra)], context)
		if low:
			self.assertTrue(high, "a larger quantity must not turn a breach into a pass")
			self.assertLessEqual(low[0].projected, high[0].projected)

	@given(caps, quantities, quantities, quantities)
	def test_breach_holds_exactly_when_projected_exceeds_cap(self, cap, on_hand, in_transit, qty):
		breaches = evaluate([_line(qty)], _context(cap, on_hand, in_transit))
		self.assertEqual(bool(breaches), (on_hand + in_transit + qty) > cap)

	@given(caps, quantities, quantities, quantities)
	def test_allowed_qty_is_the_largest_non_breaching_quantity(self, cap, on_hand, in_transit, qty):
		context = _context(cap, on_hand, in_transit)
		breaches = evaluate([_line(qty)], context)
		if not breaches:
			return

		self.assertEqual(evaluate([_line(breaches[0].allowed_qty)], context), [])
