from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from asn_module.barcode_process_flow.rules import evaluate_rule
from asn_module.tests.compat import UnitTestCase


class TestBarcodeProcessFlowProperties(UnitTestCase):
	@given(st.integers(min_value=1, max_value=20))
	def test_items_aggregate_count_is_deterministic(self, count):
		doc = SimpleNamespace(items=[SimpleNamespace(qty=1) for _ in range(count)])
		rule = SimpleNamespace(
			scope="items_aggregate",
			aggregate_fn="count",
			field_path="items[].qty",
			operator=">=",
			value=str(count),
		)
		self.assertTrue(evaluate_rule(doc, rule))
