from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

ALLOWED_SCOPES = {"header", "items_any", "items_all", "items_aggregate"}
ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "contains", "is_set", "exists"}
_OPERATOR_ALIASES = {
	"eq": "=",
	"ne": "!=",
	"gt": ">",
	"gte": ">=",
	"lt": "<",
	"lte": "<=",
}
_AGGREGATE_FUNCTIONS = {"exists", "count", "sum", "min", "max", "avg"}
_MISSING = object()


def evaluate_conditions(doc: Any, rules: list[Any] | tuple[Any, ...] | None) -> bool:
	"""Evaluate enabled rules for the provided document."""
	if not rules:
		return True

	for rule in rules:
		if not _is_rule_enabled(rule):
			continue
		if not _evaluate_rule(doc, rule):
			return False

	return True


def _evaluate_rule(doc: Any, rule: Any) -> bool:
	scope = str(_get_value(rule, "scope", "header") or "").strip()
	if scope not in ALLOWED_SCOPES:
		raise ValueError(f"Unsupported condition scope: {scope}")

	if scope == "header":
		return _evaluate_header_rule(doc, rule)

	items = _get_items(doc)
	if scope == "items_any":
		return any(_evaluate_item_rule(item, rule) for item in items)
	if scope == "items_all":
		return all(_evaluate_item_rule(item, rule) for item in items)
	return _evaluate_aggregate_rule(items, rule)


def _evaluate_header_rule(doc: Any, rule: Any) -> bool:
	field_path = _normalize_field_path(_get_value(rule, "field_path"), scope="header")
	left_value = _resolve_field_path(doc, field_path, default=_MISSING)
	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=left_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _evaluate_item_rule(item: Any, rule: Any) -> bool:
	field_path = _normalize_field_path(_get_value(rule, "field_path"), scope="items_any")
	left_value = _resolve_field_path(item, field_path, default=_MISSING)
	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=left_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _evaluate_aggregate_rule(items: list[Any], rule: Any) -> bool:
	aggregate_fn = str(_get_value(rule, "aggregate_fn", "") or "").strip().lower()
	if aggregate_fn not in _AGGREGATE_FUNCTIONS:
		raise ValueError(f"Unsupported aggregate function: {aggregate_fn}")

	if aggregate_fn == "exists":
		return _evaluate_exists_aggregate(items, rule)

	field_path = _normalize_field_path(_get_value(rule, "field_path"), scope="items_aggregate")
	values = _collect_values(items, field_path)
	aggregate_value = _compute_aggregate_value(aggregate_fn, values)
	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=aggregate_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _evaluate_exists_aggregate(items: list[Any], rule: Any) -> bool:
	operator = _normalize_operator(_get_value(rule, "operator"))
	if operator == "exists":
		return bool(items)

	field_path = _normalize_field_path(_get_value(rule, "field_path"), scope="items_aggregate")
	if operator == "is_set":
		return any(_is_set(_resolve_field_path(item, field_path, default=_MISSING)) for item in items)

	expected_value = _normalize_literal(_get_value(rule, "value"))
	return any(
		_apply_operator(
			operator=operator,
			left_value=_resolve_field_path(item, field_path, default=_MISSING),
			right_value=expected_value,
		)
		for item in items
	)


def _collect_values(items: list[Any], field_path: str) -> list[Any]:
	values: list[Any] = []
	for item in items:
		value = _resolve_field_path(item, field_path, default=_MISSING)
		if value is _MISSING:
			continue
		values.append(value)
	return values


def _compute_aggregate_value(aggregate_fn: str, values: list[Any]) -> Any:
	if aggregate_fn == "count":
		return len(values)

	numeric_values = [_to_number(value) for value in values if _to_number(value) is not None]

	if aggregate_fn == "sum":
		return sum(numeric_values)
	if aggregate_fn == "min":
		return min(numeric_values) if numeric_values else None
	if aggregate_fn == "max":
		return max(numeric_values) if numeric_values else None
	if aggregate_fn == "avg":
		if not numeric_values:
			return None
		return sum(numeric_values) / len(numeric_values)

	raise ValueError(f"Unsupported aggregate function: {aggregate_fn}")


def _apply_operator(operator: Any, left_value: Any, right_value: Any) -> bool:
	normalized_operator = _normalize_operator(operator)

	if normalized_operator == "exists":
		return left_value is not _MISSING
	if normalized_operator == "is_set":
		return _is_set(left_value)
	if left_value is _MISSING:
		return False

	if normalized_operator == "=":
		return left_value == right_value
	if normalized_operator == "!=":
		return left_value != right_value
	if normalized_operator == ">":
		return _safe_compare(left_value, right_value, "gt")
	if normalized_operator == ">=":
		return _safe_compare(left_value, right_value, "gte")
	if normalized_operator == "<":
		return _safe_compare(left_value, right_value, "lt")
	if normalized_operator == "<=":
		return _safe_compare(left_value, right_value, "lte")
	if normalized_operator == "in":
		return _evaluate_in(left_value, right_value)
	if normalized_operator == "contains":
		return _evaluate_contains(left_value, right_value)

	raise ValueError(f"Unsupported operator: {normalized_operator}")


def _normalize_operator(operator: Any) -> str:
	normalized = str(operator or "").strip()
	normalized = _OPERATOR_ALIASES.get(normalized, normalized)
	if normalized not in ALLOWED_OPERATORS:
		raise ValueError(f"Unsupported operator: {operator}")
	return normalized


def _safe_compare(left_value: Any, right_value: Any, op: str) -> bool:
	try:
		return _compare(left_value, right_value, op)
	except TypeError:
		left_number = _to_number(left_value)
		right_number = _to_number(right_value)
		if left_number is None or right_number is None:
			return False
		return _compare(left_number, right_number, op)


def _compare(left_value: Any, right_value: Any, op: str) -> bool:
	if op == "gt":
		return left_value > right_value
	if op == "gte":
		return left_value >= right_value
	if op == "lt":
		return left_value < right_value
	return left_value <= right_value


def _evaluate_in(left_value: Any, right_value: Any) -> bool:
	if right_value is None:
		return False
	if isinstance(right_value, str):
		right_value = [part.strip() for part in right_value.split(",") if part.strip()]
	if isinstance(right_value, (list, tuple, set)):
		return left_value in right_value
	return False


def _evaluate_contains(left_value: Any, right_value: Any) -> bool:
	if left_value in (_MISSING, None):
		return False
	if isinstance(left_value, str):
		return str(right_value) in left_value
	if isinstance(left_value, dict):
		return right_value in left_value
	if isinstance(left_value, Iterable):
		return right_value in left_value
	return False


def _normalize_literal(value: Any) -> Any:
	if not isinstance(value, str):
		return value

	trimmed = value.strip()
	if not trimmed:
		return ""

	try:
		return json.loads(trimmed)
	except json.JSONDecodeError:
		return value


def _resolve_field_path(source: Any, field_path: str, *, default: Any = _MISSING) -> Any:
	if not field_path:
		return source

	current = source
	for segment in field_path.split("."):
		segment = segment.strip()
		if not segment:
			continue
		if current is None:
			return default

		if isinstance(current, dict):
			if segment not in current:
				return default
			current = current.get(segment)
			continue

		if hasattr(current, segment):
			current = getattr(current, segment)
			continue

		getter = getattr(current, "get", None)
		if callable(getter):
			value = getter(segment, _MISSING)
			if value is _MISSING:
				return default
			current = value
			continue

		return default

	return current


def _normalize_field_path(field_path: Any, *, scope: str) -> str:
	path = str(field_path or "").strip()
	if scope == "header" and path.startswith("header."):
		return path[7:]
	if scope in {"items_any", "items_all", "items_aggregate"} and path.startswith("items."):
		return path[6:]
	return path


def _is_set(value: Any) -> bool:
	if value is _MISSING or value is None:
		return False
	if isinstance(value, str):
		return bool(value.strip())
	if isinstance(value, (list, tuple, set, dict)):
		return bool(value)
	return True


def _to_number(value: Any) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _is_rule_enabled(rule: Any) -> bool:
	raw_value = _get_value(rule, "is_enabled", 1)
	return _coerce_bool(raw_value, default=True)


def _coerce_bool(value: Any, *, default: bool) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		normalized = value.strip().lower()
		if normalized in {"0", "false", "no", "off", ""}:
			return False
		if normalized in {"1", "true", "yes", "on"}:
			return True
	return bool(value)


def _get_items(doc: Any) -> list[Any]:
	items = _resolve_field_path(doc, "items", default=[])
	if not items:
		return []
	if isinstance(items, list):
		return items
	if isinstance(items, tuple):
		return list(items)
	if isinstance(items, Iterable) and not isinstance(items, (str, bytes, dict)):
		return list(items)
	return []


def _get_value(source: Any, fieldname: str, default: Any = None) -> Any:
	if isinstance(source, dict):
		return source.get(fieldname, default)
	return getattr(source, fieldname, default)
