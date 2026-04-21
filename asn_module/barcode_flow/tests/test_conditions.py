from types import SimpleNamespace
from unittest import TestCase

from asn_module.barcode_flow.conditions import evaluate_conditions


class TestBarcodeFlowConditions(TestCase):
	def _doc(self):
		return SimpleNamespace(
			status="Open",
			company=SimpleNamespace(name="COMP-1"),
			items=[
				{"item_code": "ITEM-1", "qty": 1, "inspection_required_before_purchase": 0},
				{"item_code": "ITEM-2", "qty": 5, "inspection_required_before_purchase": 1},
			],
		)

	def test_header_rule(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "header",
					"field_path": "company.name",
					"operator": "=",
					"value": "COMP-1",
				}
			],
		)

		self.assertTrue(ok)

	def test_items_any_true_when_one_item_matches(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "items_any",
					"field_path": "inspection_required_before_purchase",
					"operator": "=",
					"value": 1,
				}
			],
		)

		self.assertTrue(ok)

	def test_items_all_false_when_one_item_fails(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "items_all",
					"field_path": "qty",
					"operator": ">=",
					"value": 2,
				}
			],
		)

		self.assertFalse(ok)

	def test_items_aggregate_exists(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "items_aggregate",
					"aggregate_fn": "exists",
					"field_path": "inspection_required_before_purchase",
					"operator": "exists",
				}
			],
		)

		self.assertTrue(ok)

	def test_disabled_rule_skipped(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "header",
					"field_path": "status",
					"operator": "=",
					"value": "Closed",
					"is_enabled": 0,
				},
				{
					"scope": "header",
					"field_path": "status",
					"operator": "=",
					"value": "Open",
					"is_enabled": 1,
				},
			],
		)

		self.assertTrue(ok)

	def test_not_in_operator(self):
		ok = evaluate_conditions(
			self._doc(),
			[
				{
					"scope": "header",
					"field_path": "status",
					"operator": "not_in",
					"value": ["Closed", "Cancelled"],
				}
			],
		)

		self.assertTrue(ok)

	def test_items_aggregate_exists_false_when_field_missing(self):
		doc = SimpleNamespace(
			items=[
				{"item_code": "ITEM-1", "qty": 1},
				{"item_code": "ITEM-2", "qty": 5},
			]
		)
		ok = evaluate_conditions(
			doc,
			[
				{
					"scope": "items_aggregate",
					"aggregate_fn": "exists",
					"field_path": "inspection_required_before_purchase",
					"operator": "exists",
				}
			],
		)

		self.assertFalse(ok)

	def test_items_all_false_when_no_items(self):
		doc = SimpleNamespace(items=[])
		ok = evaluate_conditions(
			doc,
			[
				{
					"scope": "items_all",
					"field_path": "qty",
					"operator": ">=",
					"value": 1,
				}
			],
		)

		self.assertFalse(ok)

	def test_numeric_aggregate_fails_on_non_numeric_values(self):
		doc = SimpleNamespace(items=[{"qty": 1}, {"qty": "bad"}])
		ok = evaluate_conditions(
			doc,
			[
				{
					"scope": "items_aggregate",
					"aggregate_fn": "sum",
					"field_path": "qty",
					"operator": ">",
					"value": 0,
				}
			],
		)

		self.assertFalse(ok)

	def test_unsupported_operator_raises(self):
		with self.assertRaises(ValueError):
			evaluate_conditions(
				self._doc(),
				[
					{
						"scope": "header",
						"field_path": "status",
						"operator": "regex",
						"value": "^O",
					}
				],
			)
