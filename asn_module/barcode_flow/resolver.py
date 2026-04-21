from dataclasses import dataclass
from typing import Any

import frappe
from frappe.utils import cint

from asn_module.barcode_flow.errors import AmbiguousFlowScopeError, NoMatchingFlowError

SCOPE_FIELDS = ("company", "warehouse", "supplier_type")


@dataclass(frozen=True)
class _ScopeCandidate:
	flow: Any
	flow_name: str
	scope_key: str
	specificity: int
	priority: int
	is_default: bool


def resolve_flow(context: dict) -> Any:
	"""Resolve one active Barcode Flow Definition for the provided context."""
	normalized_context = {fieldname: _normalize_value(context.get(fieldname)) for fieldname in SCOPE_FIELDS}
	matching_candidates: list[_ScopeCandidate] = []
	global_default_candidates: list[_ScopeCandidate] = []

	for flow in _get_active_flow_definitions():
		if not _is_enabled(flow):
			continue

		for scope in _get_row_value(flow, "scopes") or []:
			if not _is_enabled(scope):
				continue
			if not _scope_matches(scope, normalized_context):
				continue

			candidate = _build_candidate(flow=flow, scope=scope)
			if candidate.specificity > 0:
				matching_candidates.append(candidate)
			elif candidate.is_default:
				global_default_candidates.append(candidate)

	if matching_candidates:
		return _pick_winner(matching_candidates, context)

	if len(global_default_candidates) == 1:
		return global_default_candidates[0].flow

	if len(global_default_candidates) > 1:
		raise AmbiguousFlowScopeError(_format_ambiguity_message(context, global_default_candidates))

	raise NoMatchingFlowError(f"No active barcode flow matches context: {context}")


def _get_active_flow_definitions() -> list[Any]:
	flow_names = frappe.get_all(
		"Barcode Flow Definition",
		filters={"is_active": 1},
		pluck="name",
		order_by="name asc",
	)
	return [frappe.get_doc("Barcode Flow Definition", flow_name) for flow_name in flow_names]


def _scope_matches(scope: Any, normalized_context: dict[str, Any]) -> bool:
	for fieldname in SCOPE_FIELDS:
		expected = _normalize_value(_get_row_value(scope, fieldname))
		if expected in (None, ""):
			continue

		if normalized_context.get(fieldname) != expected:
			return False

	return True


def _scope_specificity(scope: Any) -> int:
	return sum(
		1 for fieldname in SCOPE_FIELDS if _normalize_value(_get_row_value(scope, fieldname)) not in (None, "")
	)


def _build_candidate(*, flow: Any, scope: Any) -> _ScopeCandidate:
	flow_name = (_get_row_value(flow, "name") or _get_row_value(flow, "flow_name") or "<unknown-flow>").strip()
	scope_key = (_get_row_value(scope, "scope_key") or "<unknown-scope>").strip()

	return _ScopeCandidate(
		flow=flow,
		flow_name=flow_name,
		scope_key=scope_key,
		specificity=_scope_specificity(scope),
		priority=cint(_get_row_value(scope, "priority") or 0),
		is_default=bool(cint(_get_row_value(scope, "is_default") or 0)),
	)


def _pick_winner(candidates: list[_ScopeCandidate], context: dict) -> Any:
	max_specificity = max(candidate.specificity for candidate in candidates)
	specificity_winners = [
		candidate for candidate in candidates if candidate.specificity == max_specificity
	]

	max_priority = max(candidate.priority for candidate in specificity_winners)
	priority_winners = [candidate for candidate in specificity_winners if candidate.priority == max_priority]

	if len(priority_winners) == 1:
		return priority_winners[0].flow

	default_winners = [candidate for candidate in priority_winners if candidate.is_default]
	if len(default_winners) == 1:
		return default_winners[0].flow

	raise AmbiguousFlowScopeError(_format_ambiguity_message(context, priority_winners))


def _format_ambiguity_message(context: dict, candidates: list[_ScopeCandidate]) -> str:
	choices = ", ".join(sorted(f"{candidate.flow_name}:{candidate.scope_key}" for candidate in candidates))
	return f"Ambiguous barcode flow resolution for context {context}. Matching scopes: {choices}"


def _is_enabled(row: Any) -> bool:
	for fieldname in ("is_active", "enabled"):
		value = _get_row_value(row, fieldname, default=None)
		if value is not None:
			return bool(cint(value))

	return True


def _normalize_value(value: Any) -> Any:
	if isinstance(value, str):
		return value.strip()
	return value


def _get_row_value(row: Any, fieldname: str, *, default: Any = "") -> Any:
	if isinstance(row, dict):
		return row.get(fieldname, default)

	return getattr(row, fieldname, default)
