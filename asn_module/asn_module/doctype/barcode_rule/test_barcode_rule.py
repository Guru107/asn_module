from types import SimpleNamespace
from unittest import TestCase

import frappe

from asn_module.asn_module.doctype.barcode_rule.barcode_rule import BarcodeRule


def _build_rule(**overrides) -> SimpleNamespace:
	values = {
		"rule_name": " PR Submitted ",
		"scope": "header",
		"field_path": " docstatus ",
		"aggregate_fn": "",
		"operator": "=",
		"value": "1",
	}
	values.update(overrides)
	return SimpleNamespace(**values)


class TestBarcodeRuleValidation(TestCase):
	def test_autoname_uses_trimmed_rule_name(self):
		doc = _build_rule(rule_name="  Rule A  ")
		BarcodeRule.autoname(doc)
		self.assertEqual(doc.name, "Rule A")

	def test_validate_normalizes_fields(self):
		doc = _build_rule(scope=" items_aggregate ", aggregate_fn=" SUM ", field_path=" items[].qty ")
		BarcodeRule.validate(doc)
		self.assertEqual(doc.rule_name, "PR Submitted")
		self.assertEqual(doc.scope, "items_aggregate")
		self.assertEqual(doc.aggregate_fn, "sum")
		self.assertEqual(doc.field_path, "items[].qty")

	def test_validate_requires_rule_name(self):
		doc = _build_rule(rule_name=" ")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_requires_field_path(self):
		doc = _build_rule(field_path=" ")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_rejects_invalid_scope(self):
		doc = _build_rule(scope="items")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_rejects_invalid_operator(self):
		doc = _build_rule(operator="bad")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_rejects_invalid_aggregate_fn(self):
		doc = _build_rule(scope="items_aggregate", aggregate_fn="median")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_requires_aggregate_fn_for_items_aggregate(self):
		doc = _build_rule(scope="items_aggregate", aggregate_fn="")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_rejects_aggregate_fn_for_non_aggregate_scopes(self):
		doc = _build_rule(scope="header", aggregate_fn="count")
		with self.assertRaises(frappe.ValidationError):
			BarcodeRule.validate(doc)

	def test_validate_rejects_exists_style_operators_for_numeric_aggregates(self):
		for aggregate_fn in ("count", "sum", "min", "max", "avg"):
			doc = _build_rule(
				scope="items_aggregate",
				aggregate_fn=aggregate_fn,
				operator="exists",
				field_path="items[].qty",
			)
			with self.assertRaises(frappe.ValidationError):
				BarcodeRule.validate(doc)

	def test_validate_allows_exists_operator_for_exists_aggregate(self):
		doc = _build_rule(
			scope="items_aggregate",
			aggregate_fn="exists",
			operator="exists",
			field_path="items[].inspection_required_before_purchase",
		)
		BarcodeRule.validate(doc)
