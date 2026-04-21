from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import UnitTestCase
from hypothesis import given
from hypothesis import strategies as st

from asn_module.barcode_flow.conditions import evaluate_conditions
from asn_module.barcode_flow.errors import AmbiguousFlowScopeError, NoMatchingFlowError
from asn_module.barcode_flow.resolver import resolve_flow_with_scope

_OUTCOME_STATUSES = {"resolved", "no_match", "ambiguous_error"}

_SOURCE_DOCTYPES = st.sampled_from([None, "", "  ", "ASN", " ASN ", "Purchase Receipt"])
_COMPANIES = st.sampled_from([None, "", "  ", "COMP-1", " COMP-1 ", "COMP-2"])
_WAREHOUSES = st.sampled_from([None, "", "WH-1", " WH-1 ", "WH-2"])
_SUPPLIER_TYPES = st.sampled_from([None, "", "Retail", " Retail ", "Distributor"])

_SIMPLE_LITERAL = st.one_of(
	st.none(),
	st.booleans(),
	st.integers(min_value=-3, max_value=6),
	st.text(alphabet="ABC xyz,-", max_size=6),
)

_ITEM_VALUE = st.one_of(
	_SIMPLE_LITERAL,
	st.lists(st.integers(min_value=-2, max_value=3), max_size=3),
	st.dictionaries(
		keys=st.text(alphabet="ab", min_size=1, max_size=2),
		values=st.integers(min_value=-2, max_value=2),
		max_size=2,
	),
)

_OPERATORS = st.sampled_from(["=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_set", "exists"])


@st.composite
def _scope_specs(draw):
	return {
		"scope_key": draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12)),
		"is_active": draw(st.sampled_from([0, 1])),
		"priority": draw(st.integers(min_value=-2, max_value=5)),
		"is_default": draw(st.sampled_from([0, 1])),
		"source_doctype": draw(_SOURCE_DOCTYPES),
		"company": draw(_COMPANIES),
		"warehouse": draw(_WAREHOUSES),
		"supplier_type": draw(_SUPPLIER_TYPES),
	}


@st.composite
def _flow_specs(draw):
	flow_count = draw(st.integers(min_value=0, max_value=4))
	flows: list[dict] = []
	for _ in range(flow_count):
		scope_count = draw(st.integers(min_value=0, max_value=3))
		flows.append(
			{
				"is_active": draw(st.sampled_from([0, 1])),
				"scopes": draw(st.lists(_scope_specs(), min_size=scope_count, max_size=scope_count)),
			}
		)
	return flows


@st.composite
def _contexts(draw):
	return {
		"source_doctype": draw(_SOURCE_DOCTYPES),
		"company": draw(_COMPANIES),
		"warehouse": draw(_WAREHOUSES),
		"supplier_type": draw(_SUPPLIER_TYPES),
	}


@st.composite
def _rule_framing(draw):
	operator = draw(_OPERATORS)
	field_path = draw(st.sampled_from(["probe", "items.probe"]))
	if operator in {"in", "not_in"}:
		value = draw(
			st.one_of(
				st.none(),
				st.text(alphabet="ABC xyz,-", max_size=8),
				st.lists(_SIMPLE_LITERAL, max_size=4),
			)
		)
	elif operator in {"exists", "is_set"}:
		value = None
	else:
		value = draw(_SIMPLE_LITERAL)
	return field_path, operator, value


_ITEMS = st.lists(
	st.dictionaries(keys=st.sampled_from(["probe", "other"]), values=_ITEM_VALUE, max_size=2),
	max_size=5,
)


def _build_flows(flow_specs: list[dict]) -> list[SimpleNamespace]:
	flows: list[SimpleNamespace] = []
	for flow_idx, flow_spec in enumerate(flow_specs):
		scopes: list[SimpleNamespace] = []
		for scope_idx, scope_spec in enumerate(flow_spec["scopes"]):
			scopes.append(
				SimpleNamespace(
					scope_key=f"s{flow_idx}_{scope_idx}_{scope_spec['scope_key']}",
					is_active=scope_spec["is_active"],
					priority=scope_spec["priority"],
					is_default=scope_spec["is_default"],
					source_doctype=scope_spec["source_doctype"],
					company=scope_spec["company"],
					warehouse=scope_spec["warehouse"],
					supplier_type=scope_spec["supplier_type"],
				)
			)
		flows.append(SimpleNamespace(name=f"FLOW-{flow_idx}", is_active=flow_spec["is_active"], scopes=scopes))
	return flows


def _resolve_outcome(context: dict, flows: list[SimpleNamespace]) -> tuple[str, str | None, str | None]:
	with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
		try:
			flow, scope_key = resolve_flow_with_scope(context)
		except NoMatchingFlowError:
			return "no_match", None, None
		except AmbiguousFlowScopeError:
			return "ambiguous_error", None, None
		return "resolved", flow.name, scope_key


def _build_rule(*, scope: str, field_path: str, operator: str, value: object, aggregate_fn: str | None = None) -> dict:
	rule = {
		"scope": scope,
		"field_path": field_path,
		"operator": operator,
	}
	if aggregate_fn:
		rule["aggregate_fn"] = aggregate_fn
	if operator not in {"exists", "is_set"}:
		rule["value"] = value
	return rule


class TestBarcodeFlowProperties(UnitTestCase):
	@given(context=_contexts(), flow_specs=_flow_specs())
	def test_resolver_outcomes_are_bounded_and_deterministic(self, context, flow_specs):
		flows = _build_flows(flow_specs)

		once = _resolve_outcome(context, flows)
		twice = _resolve_outcome(context, flows)
		reversed_once = _resolve_outcome(context, list(reversed(flows)))

		self.assertIn(once[0], _OUTCOME_STATUSES)
		self.assertEqual(once, twice)
		self.assertEqual(once, reversed_once)

		if once[0] == "resolved":
			self.assertIn(once[1], {flow.name for flow in flows})
			self.assertTrue(once[2])

	@given(items=_ITEMS, framing=_rule_framing())
	def test_items_any_and_exists_aggregate_equivalence(self, items, framing):
		field_path, operator, value = framing
		doc = {"items": items}

		items_any_rule = _build_rule(
			scope="items_any",
			field_path=field_path,
			operator=operator,
			value=value,
		)
		aggregate_exists_rule = _build_rule(
			scope="items_aggregate",
			aggregate_fn="exists",
			field_path=field_path,
			operator=operator,
			value=value,
		)

		items_any_result = evaluate_conditions(doc, [items_any_rule])
		aggregate_exists_result = evaluate_conditions(doc, [aggregate_exists_rule])

		self.assertEqual(items_any_result, aggregate_exists_result)
