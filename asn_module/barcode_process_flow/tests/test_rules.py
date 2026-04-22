from types import SimpleNamespace

from frappe.tests import UnitTestCase

from asn_module.barcode_process_flow.rules import evaluate_rule


class TestRules(UnitTestCase):
	def test_items_any_rule_true_when_any_item_matches(self):
		doc = SimpleNamespace(items=[SimpleNamespace(item_code="A"), SimpleNamespace(item_code="B")])
		rule = SimpleNamespace(scope="items_any", field_path="items[].item_code", operator="=", value="B")
		self.assertTrue(evaluate_rule(doc, rule))

	def test_items_aggregate_count_rule(self):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=1), SimpleNamespace(qty=3)])
		rule = SimpleNamespace(
			scope="items_aggregate", aggregate_fn="count", field_path="items[].qty", operator=">=", value="2"
		)
		self.assertTrue(evaluate_rule(doc, rule))
