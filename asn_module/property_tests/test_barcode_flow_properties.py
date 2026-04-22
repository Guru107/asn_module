from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import cint
from hypothesis import example, given
from hypothesis import strategies as st

from asn_module.asn_module.doctype.barcode_flow_action_binding.barcode_flow_action_binding import (
	BarcodeFlowActionBinding,
)
from asn_module.asn_module.doctype.barcode_flow_transition.barcode_flow_transition import (
	BarcodeFlowTransition,
)
from asn_module.asn_module.doctype.qr_action_definition.qr_action_definition import (
	QRActionDefinition,
)
from asn_module.barcode_flow.conditions import evaluate_conditions
from asn_module.barcode_flow.errors import AmbiguousFlowScopeError, NoMatchingFlowError
from asn_module.barcode_flow.resolver import resolve_flow_with_scope
from asn_module.property_tests import settings as _property_settings

_OUTCOME_STATUSES = {"resolved", "no_match", "ambiguous_error"}
_SCOPE_MATCH_FIELDS = ("source_doctype", "company", "warehouse", "supplier_type")
_SCOPE_SPECIFICITY_FIELDS = ("company", "warehouse", "supplier_type")

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

_OPERATORS = st.sampled_from(
	["=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_set", "exists"]
)
_FLOW_IDS = st.lists(st.integers(min_value=1, max_value=24), min_size=1, max_size=4, unique=True)
_TRANSITION_LINK_FIELDS = st.sampled_from(
	["source_node", "target_node", "condition", "field_map", "action_binding"]
)
_BINDING_LINK_FIELDS = st.sampled_from(["target_node", "target_transition"])
_FLOW_ID = st.integers(min_value=1, max_value=24)


@st.composite
def _scope_specs(draw):
	return {
		"scope_key": draw(
			st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12)
		),
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
		flows.append(
			SimpleNamespace(name=f"FLOW-{flow_idx}", is_active=flow_spec["is_active"], scopes=scopes)
		)
	return flows


def _get_value(source: object, fieldname: str, default: object = None) -> object:
	if isinstance(source, dict):
		return source.get(fieldname, default)
	return getattr(source, fieldname, default)


def _normalize_value(value: object) -> object:
	if isinstance(value, str):
		return value.strip()
	return value


def _is_enabled(row: object) -> bool:
	for fieldname in ("is_active", "enabled"):
		value = _get_value(row, fieldname, default=None)
		if value is not None:
			return bool(cint(value))
	return True


def _scope_matches(scope: object, normalized_context: dict[str, object]) -> bool:
	for fieldname in _SCOPE_MATCH_FIELDS:
		expected = _normalize_value(_get_value(scope, fieldname, ""))
		if expected in (None, ""):
			continue
		if normalized_context.get(fieldname) != expected:
			return False
	return True


def _scope_specificity(scope: object) -> int:
	return sum(
		1
		for fieldname in _SCOPE_SPECIFICITY_FIELDS
		if _normalize_value(_get_value(scope, fieldname, "")) not in (None, "")
	)


def _expected_resolver_outcome(
	context: dict,
	flows: list[SimpleNamespace],
) -> tuple[str, str | None, str | None]:
	normalized_context = {
		fieldname: _normalize_value(context.get(fieldname)) for fieldname in _SCOPE_MATCH_FIELDS
	}
	candidates: list[dict[str, object]] = []
	for flow in flows:
		if not _is_enabled(flow):
			continue
		for scope in _get_value(flow, "scopes", []) or []:
			if not _is_enabled(scope):
				continue
			if not _scope_matches(scope, normalized_context):
				continue
			candidates.append(
				{
					"flow_name": _get_value(flow, "name"),
					"scope_key": _get_value(scope, "scope_key"),
					"specificity": _scope_specificity(scope),
					"priority": cint(_get_value(scope, "priority", 0) or 0),
					"is_default": bool(cint(_get_value(scope, "is_default", 0) or 0)),
				}
			)

	if not candidates:
		return "no_match", None, None

	max_specificity = max(candidate["specificity"] for candidate in candidates)
	specificity_winners = [c for c in candidates if c["specificity"] == max_specificity]

	max_priority = max(candidate["priority"] for candidate in specificity_winners)
	priority_winners = [c for c in specificity_winners if c["priority"] == max_priority]
	if len(priority_winners) == 1:
		winner = priority_winners[0]
		return "resolved", winner["flow_name"], winner["scope_key"]

	default_winners = [c for c in priority_winners if c["is_default"]]
	if len(default_winners) == 1:
		winner = default_winners[0]
		return "resolved", winner["flow_name"], winner["scope_key"]

	return "ambiguous_error", None, None


def _rotate_scopes_within_flows(flows: list[SimpleNamespace]) -> list[SimpleNamespace]:
	rotated_flows: list[SimpleNamespace] = []
	for flow in flows:
		scopes = list(_get_value(flow, "scopes", []) or [])
		if len(scopes) > 1:
			scopes = scopes[1:] + scopes[:1]
		rotated_flows.append(
			SimpleNamespace(
				name=_get_value(flow, "name"),
				is_active=_get_value(flow, "is_active"),
				scopes=scopes,
			)
		)
	return rotated_flows


def _resolve_outcome(context: dict, flows: list[SimpleNamespace]) -> tuple[str, str | None, str | None]:
	with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
		try:
			flow, scope_key = resolve_flow_with_scope(context)
		except NoMatchingFlowError:
			return "no_match", None, None
		except AmbiguousFlowScopeError:
			return "ambiguous_error", None, None
		return "resolved", flow.name, scope_key


def _build_rule(
	*, scope: str, field_path: str, operator: str, value: object, aggregate_fn: str | None = None
) -> dict:
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


def _entity_name(*, flow: str, entity_code: str, key: str) -> str:
	return f"FLOW-{flow}-{entity_code}-{key}"


def _build_relational_graph(flow_ids: list[int]) -> dict[str, object]:
	graph = {
		"flows": [],
		"by_flow": {},
		"nodes": {},
		"conditions": {},
		"field_maps": {},
		"bindings": {},
		"transitions": {},
	}

	for flow_id in flow_ids:
		flow = f"FLOW-{flow_id}"
		graph["flows"].append(flow)
		scan_node = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="NODE", key="scan"),
			flow=flow,
			node_key="scan",
		)
		received_node = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="NODE", key="received"),
			flow=flow,
			node_key="received",
		)
		condition = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="COND", key="allow-received"),
			flow=flow,
			condition_key="allow-received",
		)
		field_map = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="MAP", key="warehouse-map"),
			flow=flow,
			map_key="warehouse-map",
		)
		handler_binding = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="BIND", key="handler-binding"),
			flow=flow,
			binding_key="handler-binding",
			target_node="",
			target_transition="",
		)
		transition = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="TRANS", key="scan-to-received"),
			flow=flow,
			transition_key="scan-to-received",
			source_node=scan_node.name,
			target_node=received_node.name,
			condition=condition.name,
			field_map=field_map.name,
			action_binding=handler_binding.name,
		)
		node_binding = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="BIND", key="enter-received"),
			flow=flow,
			binding_key="enter-received",
			target_node=received_node.name,
			target_transition="",
		)
		transition_binding = SimpleNamespace(
			name=_entity_name(flow=flow, entity_code="BIND", key="after-scan"),
			flow=flow,
			binding_key="after-scan",
			target_node="",
			target_transition=transition.name,
		)

		for row in (scan_node, received_node):
			graph["nodes"][row.name] = row
		graph["conditions"][condition.name] = condition
		graph["field_maps"][field_map.name] = field_map
		for row in (handler_binding, node_binding, transition_binding):
			graph["bindings"][row.name] = row
		graph["transitions"][transition.name] = transition
		graph["by_flow"][flow] = {
			"nodes": {"scan": scan_node.name, "received": received_node.name},
			"condition": condition.name,
			"field_map": field_map.name,
			"bindings": {
				"handler": handler_binding.name,
				"node": node_binding.name,
				"transition": transition_binding.name,
			},
			"transition": transition.name,
		}

	return graph


def _same_flow_link_violations(graph: dict[str, object]) -> list[tuple[str, str]]:
	violations: list[tuple[str, str]] = []

	for transition in graph["transitions"].values():
		for fieldname, pool in (
			("source_node", "nodes"),
			("target_node", "nodes"),
			("condition", "conditions"),
			("field_map", "field_maps"),
			("action_binding", "bindings"),
		):
			link_name = _get_value(transition, fieldname, "")
			if not link_name:
				continue
			linked = graph[pool].get(link_name)
			if not linked or _get_value(linked, "flow") != _get_value(transition, "flow"):
				violations.append((_get_value(transition, "name"), fieldname))

	for binding in graph["bindings"].values():
		for fieldname, pool in (("target_node", "nodes"), ("target_transition", "transitions")):
			link_name = _get_value(binding, fieldname, "")
			if not link_name:
				continue
			linked = graph[pool].get(link_name)
			if not linked or _get_value(linked, "flow") != _get_value(binding, "flow"):
				violations.append((_get_value(binding, "name"), fieldname))

	return violations


def _delete_blockers(graph: dict[str, object]) -> dict[str, dict[str, list[str]]]:
	blockers = {
		"nodes": {},
		"conditions": {},
		"field_maps": {},
		"bindings": {},
		"transitions": {},
	}

	def _add(pool: str, entity_name: str, ref: str) -> None:
		if not entity_name:
			return
		blockers[pool].setdefault(entity_name, []).append(ref)

	for transition in graph["transitions"].values():
		transition_name = _get_value(transition, "name")
		_add("nodes", _get_value(transition, "source_node", ""), f"{transition_name}.source_node")
		_add("nodes", _get_value(transition, "target_node", ""), f"{transition_name}.target_node")
		_add("conditions", _get_value(transition, "condition", ""), f"{transition_name}.condition")
		_add("field_maps", _get_value(transition, "field_map", ""), f"{transition_name}.field_map")
		_add("bindings", _get_value(transition, "action_binding", ""), f"{transition_name}.action_binding")

	for binding in graph["bindings"].values():
		binding_name = _get_value(binding, "name")
		_add("nodes", _get_value(binding, "target_node", ""), f"{binding_name}.target_node")
		_add(
			"transitions",
			_get_value(binding, "target_transition", ""),
			f"{binding_name}.target_transition",
		)

	return blockers


def _detach_flow_references(graph: dict[str, object], *, flow: str) -> dict[str, object]:
	detached = deepcopy(graph)

	for transition in detached["transitions"].values():
		if _get_value(transition, "flow") != flow:
			continue
		transition.source_node = ""
		transition.target_node = ""
		transition.condition = ""
		transition.field_map = ""
		transition.action_binding = ""

	for binding in detached["bindings"].values():
		if _get_value(binding, "flow") != flow:
			continue
		binding.target_node = ""
		binding.target_transition = ""

	return detached


class TestBarcodeFlowProperties(UnitTestCase):
	@given(context=_contexts(), flow_specs=_flow_specs())
	def test_resolver_outcomes_are_bounded_and_deterministic(self, context, flow_specs):
		flows = _build_flows(flow_specs)
		rotated_scope_flows = _rotate_scopes_within_flows(flows)
		expected = _expected_resolver_outcome(context, flows)

		once = _resolve_outcome(context, flows)
		twice = _resolve_outcome(context, flows)
		reversed_once = _resolve_outcome(context, list(reversed(flows)))
		rotated_scope_once = _resolve_outcome(context, rotated_scope_flows)
		reversed_rotated_once = _resolve_outcome(context, list(reversed(rotated_scope_flows)))

		for outcome in (once, twice, reversed_once, rotated_scope_once, reversed_rotated_once):
			self.assertIn(outcome[0], _OUTCOME_STATUSES)
			self.assertEqual(outcome, expected)

		if once[0] == "resolved":
			self.assertIn(once[1], {flow.name for flow in flows})
			self.assertTrue(once[2])

	@given(items=_ITEMS, framing=_rule_framing())
	@example(items=[{"probe": [1, 2, 3]}], framing=("probe", "=", [1, 2, 3]))
	@example(items=[{"probe": {"a": 1}}], framing=("items.probe", "!=", {"a": 2}))
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

	@given(flow_ids=_FLOW_IDS)
	def test_modeled_relational_graphs_preserve_same_flow_links(self, flow_ids):
		graph = _build_relational_graph(flow_ids)

		self.assertEqual(_same_flow_link_violations(graph), [])

	@given(
		flow_ids=st.lists(st.integers(min_value=1, max_value=24), min_size=2, max_size=4, unique=True),
		link_field=_TRANSITION_LINK_FIELDS,
	)
	def test_cross_flow_transition_links_are_detected(self, flow_ids, link_field):
		graph = _build_relational_graph(flow_ids)
		first_flow, second_flow = graph["flows"][:2]
		transition_name = graph["by_flow"][first_flow]["transition"]
		transition = graph["transitions"][transition_name]
		foreign_targets = {
			"source_node": graph["by_flow"][second_flow]["nodes"]["scan"],
			"target_node": graph["by_flow"][second_flow]["nodes"]["received"],
			"condition": graph["by_flow"][second_flow]["condition"],
			"field_map": graph["by_flow"][second_flow]["field_map"],
			"action_binding": graph["by_flow"][second_flow]["bindings"]["handler"],
		}

		setattr(transition, link_field, foreign_targets[link_field])

		self.assertIn((transition.name, link_field), _same_flow_link_violations(graph))

	@given(
		flow_ids=st.lists(st.integers(min_value=1, max_value=24), min_size=2, max_size=4, unique=True),
		link_field=_BINDING_LINK_FIELDS,
	)
	def test_cross_flow_binding_links_are_detected(self, flow_ids, link_field):
		graph = _build_relational_graph(flow_ids)
		first_flow, second_flow = graph["flows"][:2]
		binding_key = "node" if link_field == "target_node" else "transition"
		binding_name = graph["by_flow"][first_flow]["bindings"][binding_key]
		binding = graph["bindings"][binding_name]
		foreign_targets = {
			"target_node": graph["by_flow"][second_flow]["nodes"]["received"],
			"target_transition": graph["by_flow"][second_flow]["transition"],
		}

		setattr(binding, link_field, foreign_targets[link_field])

		self.assertIn((binding.name, link_field), _same_flow_link_violations(graph))

	@given(flow_ids=_FLOW_IDS)
	def test_referenced_entities_require_detach_before_delete(self, flow_ids):
		graph = _build_relational_graph(flow_ids)
		blockers = _delete_blockers(graph)
		first_flow = graph["flows"][0]
		owned = graph["by_flow"][first_flow]

		self.assertTrue(blockers["nodes"].get(owned["nodes"]["scan"]))
		self.assertTrue(blockers["nodes"].get(owned["nodes"]["received"]))
		self.assertTrue(blockers["conditions"].get(owned["condition"]))
		self.assertTrue(blockers["field_maps"].get(owned["field_map"]))
		self.assertTrue(blockers["bindings"].get(owned["bindings"]["handler"]))
		self.assertTrue(blockers["transitions"].get(owned["transition"]))

		detached = _detach_flow_references(graph, flow=first_flow)
		detached_blockers = _delete_blockers(detached)

		self.assertEqual(detached_blockers["nodes"].get(owned["nodes"]["scan"], []), [])
		self.assertEqual(detached_blockers["nodes"].get(owned["nodes"]["received"], []), [])
		self.assertEqual(detached_blockers["conditions"].get(owned["condition"], []), [])
		self.assertEqual(detached_blockers["field_maps"].get(owned["field_map"], []), [])
		self.assertEqual(detached_blockers["bindings"].get(owned["bindings"]["handler"], []), [])
		self.assertEqual(detached_blockers["transitions"].get(owned["transition"], []), [])

	@given(flow_id=_FLOW_ID, is_same_flow=st.booleans())
	def test_transition_link_validator_enforces_same_flow(self, flow_id, is_same_flow):
		transition = object.__new__(BarcodeFlowTransition)
		transition.flow = f"FLOW-{flow_id}"
		link_flow = transition.flow if is_same_flow else f"FLOW-{flow_id + 100}"

		with patch(
			"asn_module.asn_module.doctype.barcode_flow_transition.barcode_flow_transition.frappe.db.get_value",
			return_value=link_flow,
		):
			if is_same_flow:
				BarcodeFlowTransition._validate_link_flow(
					transition, "Barcode Flow Node", "FLOW-TEST-NODE", "Source Node"
				)
				return

			with self.assertRaises(frappe.ValidationError):
				BarcodeFlowTransition._validate_link_flow(
					transition, "Barcode Flow Node", "FLOW-TEST-NODE", "Source Node"
				)

	@given(flow_id=_FLOW_ID, is_same_flow=st.booleans())
	def test_action_binding_link_validator_enforces_same_flow(self, flow_id, is_same_flow):
		binding = object.__new__(BarcodeFlowActionBinding)
		binding.flow = f"FLOW-{flow_id}"
		link_flow = binding.flow if is_same_flow else f"FLOW-{flow_id + 100}"

		with patch(
			"asn_module.asn_module.doctype.barcode_flow_action_binding.barcode_flow_action_binding.frappe.db.get_value",
			return_value=link_flow,
		):
			if is_same_flow:
				BarcodeFlowActionBinding._validate_link_flow(
					binding, "Barcode Flow Transition", "FLOW-TEST-TRANS", "Target Transition"
				)
				return

			with self.assertRaises(frappe.ValidationError):
				BarcodeFlowActionBinding._validate_link_flow(
					binding, "Barcode Flow Transition", "FLOW-TEST-TRANS", "Target Transition"
				)

	@given(has_transition_refs=st.booleans(), has_binding_refs=st.booleans())
	def test_qr_action_delete_guard_blocks_until_references_are_removed(
		self, has_transition_refs, has_binding_refs
	):
		action = object.__new__(QRActionDefinition)
		action.name = "ACT-test"

		def _get_all(doctype, **_kwargs):
			if doctype == "Barcode Flow Transition":
				return ["FLOW-1-TRANS"] if has_transition_refs else []
			if doctype == "Barcode Flow Action Binding":
				return ["FLOW-1-BIND"] if has_binding_refs else []
			return []

		with patch(
			"asn_module.asn_module.doctype.qr_action_definition.qr_action_definition.frappe.get_all",
			side_effect=_get_all,
		):
			if has_transition_refs or has_binding_refs:
				with self.assertRaises(frappe.ValidationError):
					QRActionDefinition.on_trash(action)
				return

			QRActionDefinition.on_trash(action)
