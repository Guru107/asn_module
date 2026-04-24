from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow import rules
from asn_module.tests.compat import UnitTestCase


class TestRules(UnitTestCase):
	def test_empty_rule_returns_true(self):
		self.assertTrue(rules.evaluate_rule(SimpleNamespace(), None))

	def test_unsupported_scope_raises(self):
		doc = SimpleNamespace(items=[])
		rule = SimpleNamespace(scope="invalid", field_path="x", operator="=", value="1")
		with self.assertRaises(ValueError):
			rules.evaluate_rule(doc, rule)

	def test_header_rule_with_header_prefix(self):
		doc = SimpleNamespace(status="Submitted")
		rule = SimpleNamespace(scope="header", field_path="header.status", operator="=", value="Submitted")
		self.assertTrue(rules.evaluate_rule(doc, rule))

	def test_items_any_rule_false_when_no_match(self):
		doc = SimpleNamespace(items=[SimpleNamespace(item_code="A"), SimpleNamespace(item_code="B")])
		rule = SimpleNamespace(scope="items_any", field_path="items[].item_code", operator="=", value="Z")
		self.assertFalse(rules.evaluate_rule(doc, rule))

	def test_items_any_rule_true_when_any_item_matches(self):
		doc = SimpleNamespace(items=[SimpleNamespace(item_code="A"), SimpleNamespace(item_code="B")])
		rule = SimpleNamespace(scope="items_any", field_path="items[].item_code", operator="=", value="B")
		self.assertTrue(rules.evaluate_rule(doc, rule))

	def test_items_all_rule_requires_non_empty_and_all_match(self):
		empty_doc = SimpleNamespace(items=[])
		rule = SimpleNamespace(scope="items_all", field_path="items[].flag", operator="=", value="1")
		self.assertFalse(rules.evaluate_rule(empty_doc, rule))

		doc = SimpleNamespace(items=[SimpleNamespace(flag=1), SimpleNamespace(flag=1)])
		self.assertTrue(rules.evaluate_rule(doc, rule))

		doc_mixed = SimpleNamespace(items=[SimpleNamespace(flag=1), SimpleNamespace(flag=0)])
		self.assertFalse(rules.evaluate_rule(doc_mixed, rule))

	def test_items_aggregate_count_rule(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=1), SimpleNamespace(qty=3)])
		rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="count", field_path="items[].qty", operator=">=", value="2"
		)
		self.assertTrue(rules.evaluate_rule(doc, rule))

	def test_items_aggregate_exists_rule(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=1), SimpleNamespace()])
		rule = SimpleNamespace(
			scope="items_aggregate",
			aggregate_fn="exists",
			field_path="items[].qty",
			operator="=",
			value="true",
		)
		self.assertTrue(rules.evaluate_rule(doc, rule))

		doc_missing = SimpleNamespace(items=[SimpleNamespace(), SimpleNamespace()])
		rule_exists_op = SimpleNamespace(
			scope="items_aggregate",
			aggregate_fn="exists",
			field_path="items[].qty",
			operator="exists",
			value="true",
		)
		self.assertFalse(rules.evaluate_rule(doc_missing, rule_exists_op))

		rule_is_set_op = SimpleNamespace(
			scope="items_aggregate",
			aggregate_fn="exists",
			field_path="items[].qty",
			operator="is_set",
			value="true",
		)
		self.assertFalse(rules.evaluate_rule(doc_missing, rule_is_set_op))

	def test_items_aggregate_numeric_functions(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=2), SimpleNamespace(qty=4)])
		sum_rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="sum", field_path="items[].qty", operator="=", value="6"
		)
		min_rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="min", field_path="items[].qty", operator="=", value="2"
		)
		max_rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="max", field_path="items[].qty", operator="=", value="4"
		)
		avg_rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="avg", field_path="items[].qty", operator="=", value="3"
		)
		self.assertTrue(rules.evaluate_rule(doc, sum_rule))
		self.assertTrue(rules.evaluate_rule(doc, min_rule))
		self.assertTrue(rules.evaluate_rule(doc, max_rule))
		self.assertTrue(rules.evaluate_rule(doc, avg_rule))

	def test_items_aggregate_invalid_function_raises(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=1)])
		rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="bad", field_path="items[].qty", operator="=", value="1"
		)
		with self.assertRaises(ValueError):
			rules.evaluate_rule(doc, rule)

	def test_items_aggregate_non_numeric_values_return_false(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty="abc")])
		rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="sum", field_path="items[].qty", operator=">", value="0"
		)
		self.assertFalse(rules.evaluate_rule(doc, rule))

	def test_operator_helpers_cover_branches(self):
		self.assertTrue(rules._apply_operator("exists", 1, None))
		self.assertFalse(rules._apply_operator("is_set", "", None))
		self.assertFalse(rules._apply_operator("=", rules._MISSING, "x"))
		self.assertTrue(rules._apply_operator("!=", 1, 2))
		self.assertTrue(rules._apply_operator("in", "A", "A,B"))
		self.assertTrue(rules._apply_operator("not_in", "Z", ["A", "B"]))
		self.assertTrue(rules._apply_operator("contains", "ABC", "B"))
		self.assertTrue(rules._apply_operator("contains", {"k": 1}, "k"))
		self.assertTrue(rules._apply_operator("contains", ["x", "y"], "x"))
		self.assertFalse(rules._apply_operator("contains", 5, "x"))
		with self.assertRaises(ValueError):
			rules._apply_operator("bad", 1, 1)
		with patch("asn_module.barcode_process_flow.rules._ALLOWED_OPERATORS", {"fallback"}):
			self.assertFalse(rules._apply_operator("fallback", 1, 1))

	def test_compare_falls_back_to_float(self):
		self.assertTrue(rules._compare("3", 2, ">"))
		self.assertFalse(rules._compare("x", "y", ">"))
		self.assertTrue(rules._compare(1, 2, "<"))
		self.assertTrue(rules._compare(2, 2, "<="))
		self.assertFalse(rules._compare(object(), 2, ">"))
		self.assertTrue(rules._compare("1", 2, "<"))
		self.assertTrue(rules._compare("2", 2, "<="))

	def test_is_in_and_contains_non_container_paths(self):
		self.assertFalse(rules._is_in("A", 5))
		self.assertFalse(rules._contains(None, "x"))

	def test_normalize_helpers_and_field_resolution(self):
		self.assertEqual(rules._normalize_literal(""), "")
		self.assertEqual(rules._normalize_literal("1"), 1)
		self.assertEqual(rules._normalize_literal(1), 1)
		self.assertEqual(rules._normalize_literal("not-json"), "not-json")
		self.assertEqual(rules._normalize_literal("  not-json  "), "not-json")
		self.assertEqual(rules._normalize_field_path("header.status"), "status")
		self.assertEqual(rules._normalize_field_path("items.qty"), "qty")
		self.assertEqual(rules._normalize_field_path("items[].qty"), "qty")
		self.assertEqual(rules._normalize_field_path("plain"), "plain")

		doc = {"a": {"b": 1}}
		self.assertEqual(rules._resolve_field_path(doc, "a.b"), 1)
		self.assertIs(rules._resolve_field_path(doc, "a.c", default=rules._MISSING), rules._MISSING)

		obj = SimpleNamespace(a=SimpleNamespace(b=2))
		self.assertEqual(rules._resolve_field_path(obj, "a.b"), 2)
		self.assertIs(
			rules._resolve_field_path(SimpleNamespace(a=None), "a.b", default=rules._MISSING), rules._MISSING
		)

		class GetterOnly:
			def __init__(self):
				self.data = {"x": 7}

			def get(self, key, default=None):
				return self.data.get(key, default)

		self.assertEqual(rules._resolve_field_path(GetterOnly(), "x"), 7)
		self.assertEqual(rules._resolve_field_path(doc, ""), doc)
		self.assertEqual(rules._resolve_field_path(doc, "a..b"), 1)

		class MissingGetter:
			def get(self, _key, default=None):
				return default

		self.assertIs(
			rules._resolve_field_path(MissingGetter(), "z", default=rules._MISSING),
			rules._MISSING,
		)
		self.assertIs(
			rules._resolve_field_path(5, "z", default=rules._MISSING),
			rules._MISSING,
		)

	def test_get_items_and_get_value_helpers(self):
		self.assertEqual(rules._get_items(SimpleNamespace(items=[1, 2])), [1, 2])
		self.assertEqual(rules._get_items(SimpleNamespace(items=(x for x in [1, 2]))), [1, 2])
		self.assertEqual(rules._get_value({"a": 1}, "a"), 1)
		self.assertEqual(rules._get_value(SimpleNamespace(a=2), "a"), 2)
