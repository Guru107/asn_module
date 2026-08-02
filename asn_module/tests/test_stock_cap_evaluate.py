import unittest

from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import CapContext, Line

BRANCH = "Mumbai"
ITEM = "WIDGET"
WH = "Main - MC"


def _context(**overrides) -> CapContext:
	defaults = {
		"cap_warehouses": {BRANCH: frozenset({WH})},
		"max_stock": {ITEM: 100.0},
		"on_hand": {},
		"in_transit": {},
	}
	defaults.update(overrides)
	return CapContext(**defaults)


def _line(qty: float, idx: int = 1, warehouse: str = WH, branch: str = BRANCH) -> Line:
	return Line(branch=branch, item_code=ITEM, warehouse=warehouse, stock_qty=qty, row_idx=idx)


class TestStockCapEvaluate(unittest.TestCase):
	def test_no_cap_configured_produces_no_breach(self):
		self.assertEqual(evaluate([_line(500)], _context(max_stock={})), [])

	def test_zero_cap_is_treated_as_uncapped(self):
		self.assertEqual(evaluate([_line(500)], _context(max_stock={ITEM: 0.0})), [])

	def test_under_cap_produces_no_breach(self):
		self.assertEqual(evaluate([_line(50)], _context(on_hand={(BRANCH, ITEM): 20.0})), [])

	def test_exactly_at_cap_is_allowed(self):
		self.assertEqual(evaluate([_line(80)], _context(on_hand={(BRANCH, ITEM): 20.0})), [])

	def test_incoming_alone_breaches_cap(self):
		breaches = evaluate([_line(101)], _context())
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].projected, 101.0)
		self.assertEqual(breaches[0].cap, 100.0)

	def test_breach_only_once_in_transit_counted(self):
		context = _context(on_hand={(BRANCH, ITEM): 50.0}, in_transit={(BRANCH, ITEM): 40.0})
		self.assertEqual(evaluate([_line(10)], context), [])
		breaches = evaluate([_line(11)], context)
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].in_transit, 40.0)

	def test_breach_only_once_consumed_headroom_applied(self):
		context = _context(on_hand={(BRANCH, ITEM): 90.0})
		self.assertEqual(evaluate([_line(10)], context), [])
		breaches = evaluate([_line(10)], context, consumed={(BRANCH, ITEM): 5.0})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].projected, 105.0)

	def test_warehouse_outside_cap_warehouses_is_ignored(self):
		self.assertEqual(evaluate([_line(500, warehouse="Other - MC")], _context()), [])

	def test_branch_without_settings_is_ignored(self):
		self.assertEqual(evaluate([_line(500, branch="Delhi")], _context()), [])

	def test_multiple_lines_for_same_item_are_summed(self):
		breaches = evaluate([_line(60, idx=1), _line(50, idx=2)], _context())
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].incoming, 110.0)
		self.assertEqual(breaches[0].row_idxs, (1, 2))

	def test_allowed_qty_is_remaining_headroom(self):
		breaches = evaluate([_line(30)], _context(on_hand={(BRANCH, ITEM): 80.0}))
		self.assertEqual(breaches[0].allowed_qty, 20.0)

	def test_allowed_qty_is_zero_when_already_over_cap(self):
		breaches = evaluate([_line(5)], _context(on_hand={(BRANCH, ITEM): 200.0}))
		self.assertEqual(breaches[0].allowed_qty, 0.0)

	def test_zero_qty_line_at_already_over_cap_branch_produces_no_breach(self):
		context = _context(on_hand={(BRANCH, ITEM): 200.0})
		self.assertEqual(evaluate([_line(0)], context), [])

	def test_non_numeric_stock_qty_is_treated_as_zero_rather_than_raising(self):
		"""Line.stock_qty is typed as float but dataclasses do not enforce that at runtime.

		_as_float's fail-open except branch (TypeError/ValueError) exists precisely so a
		malformed value can never crash the evaluator; it must coerce to 0 and be skipped
		like any other non-positive quantity, not raise.
		"""
		context = _context(on_hand={(BRANCH, ITEM): 200.0})
		self.assertEqual(evaluate([_line("not-a-number")], context), [])

	def test_declaring_reported_allowed_qty_produces_no_breach(self):
		cap = 6805.89451973124
		on_hand = 266.967946622052
		in_transit = 6349.999099114582
		qty = 6063.38417754219
		context = _context(
			max_stock={ITEM: cap},
			on_hand={(BRANCH, ITEM): on_hand},
			in_transit={(BRANCH, ITEM): in_transit},
		)
		breaches = evaluate([_line(qty)], context)
		self.assertEqual(len(breaches), 1)

		allowed_qty = breaches[0].allowed_qty
		self.assertEqual(evaluate([_line(allowed_qty)], context), [])

	def test_breaches_are_sorted_deterministically(self):
		context = CapContext(
			cap_warehouses={BRANCH: frozenset({WH})},
			max_stock={"B_ITEM": 1.0, "A_ITEM": 1.0},
			on_hand={},
			in_transit={},
		)
		lines = [
			Line(branch=BRANCH, item_code="B_ITEM", warehouse=WH, stock_qty=5, row_idx=1),
			Line(branch=BRANCH, item_code="A_ITEM", warehouse=WH, stock_qty=5, row_idx=2),
		]
		self.assertEqual([b.item_code for b in evaluate(lines, context)], ["A_ITEM", "B_ITEM"])
