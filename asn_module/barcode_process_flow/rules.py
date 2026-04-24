from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

_ALLOWED_SCOPES = {"header", "items_any", "items_all", "items_aggregate"}
_ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_set", "exists"}
_AGG_FUNCTIONS = {"exists", "count", "sum", "min", "max", "avg"}
_MISSING = object()


def evaluate_rule(doc: Any, rule: Any) -> bool:
	if not rule:
		return True

	scope = str(_get_value(rule, "scope", "header") or "header").strip()
	if scope not in _ALLOWED_SCOPES:
		raise ValueError(f"Unsupported rule scope: {scope}")

	if scope == "header":
		return _evaluate_header_rule(doc, rule)

	items = list(_get_items(doc))
	if scope == "items_any":
		return any(_evaluate_item_rule(item, rule) for item in items)
	if scope == "items_all":
		return bool(items) and all(_evaluate_item_rule(item, rule) for item in items)
	return _evaluate_aggregate_rule(items, rule)


def _evaluate_header_rule(doc: Any, rule: Any) -> bool:
	left_value = _resolve_field_path(
		doc, _normalize_field_path(_get_value(rule, "field_path")), default=_MISSING
	)
	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=left_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _evaluate_item_rule(item: Any, rule: Any) -> bool:
	left_value = _resolve_field_path(
		item, _normalize_field_path(_get_value(rule, "field_path")), default=_MISSING
	)
	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=left_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _evaluate_aggregate_rule(items: list[Any], rule: Any) -> bool:
	aggregate_fn = str(_get_value(rule, "aggregate_fn", "") or "").strip().lower()
	if aggregate_fn not in _AGG_FUNCTIONS:
		raise ValueError(f"Unsupported aggregate function: {aggregate_fn}")

	field_path = _normalize_field_path(_get_value(rule, "field_path"))
	if aggregate_fn == "exists":
		left_value = any(
			_resolve_field_path(item, field_path, default=_MISSING) is not _MISSING for item in items
		)
		operator = str(_get_value(rule, "operator", "=") or "=").strip()
		if operator in {"exists", "is_set"}:
			operator = "="
			right_value = bool(_normalize_literal(_get_value(rule, "value", "true")))
		else:
			right_value = _normalize_literal(_get_value(rule, "value", "true"))
		return _apply_operator(
			operator=operator,
			left_value=left_value,
			right_value=right_value,
		)

	values = [
		value
		for item in items
		if (value := _resolve_field_path(item, field_path, default=_MISSING)) is not _MISSING
	]

	if aggregate_fn == "count":
		aggregate_value = len(values)
	else:
		numbers = [_to_float(value) for value in values]
		if any(number is None for number in numbers):
			return False
		numbers = [float(number) for number in numbers if number is not None]
		if aggregate_fn == "sum":
			aggregate_value = sum(numbers)
		elif aggregate_fn == "min":
			aggregate_value = min(numbers) if numbers else None
		elif aggregate_fn == "max":
			aggregate_value = max(numbers) if numbers else None
		else:
			aggregate_value = (sum(numbers) / len(numbers)) if numbers else None

	return _apply_operator(
		operator=_get_value(rule, "operator"),
		left_value=aggregate_value,
		right_value=_normalize_literal(_get_value(rule, "value")),
	)


def _apply_operator(operator: Any, left_value: Any, right_value: Any) -> bool:
	op = str(operator or "=").strip()
	if op not in _ALLOWED_OPERATORS:
		raise ValueError(f"Unsupported operator: {op}")

	if op == "exists":
		return left_value is not _MISSING and left_value is not None
	if op == "is_set":
		return left_value not in (_MISSING, None, "", [])
	if left_value is _MISSING:
		return False

	if op == "=":
		return left_value == right_value
	if op == "!=":
		return left_value != right_value
	if op in {">", ">=", "<", "<="}:
		return _compare(left_value, right_value, op)
	if op == "in":
		return _is_in(left_value, right_value)
	if op == "not_in":
		return not _is_in(left_value, right_value)
	if op == "contains":
		return _contains(left_value, right_value)
	return False


def _compare(left: Any, right: Any, op: str) -> bool:
	try:
		if op == ">":
			return left > right
		if op == ">=":
			return left >= right
		if op == "<":
			return left < right
		return left <= right
	except TypeError:
		left_num = _to_float(left)
		right_num = _to_float(right)
		if left_num is None or right_num is None:
			return False
		if op == ">":
			return left_num > right_num
		if op == ">=":
			return left_num >= right_num
		if op == "<":
			return left_num < right_num
		return left_num <= right_num


def _is_in(left: Any, right: Any) -> bool:
	if isinstance(right, str):
		right = [part.strip() for part in right.split(",") if part.strip()]
	if isinstance(right, (list, tuple, set)):
		return left in right
	return False


def _contains(left: Any, right: Any) -> bool:
	if isinstance(left, str):
		return str(right) in left
	if isinstance(left, dict):
		return right in left
	if isinstance(left, Iterable):
		return right in left
	return False


def _get_items(doc: Any) -> list[Any]:
	items = _get_value(doc, "items", [])
	if isinstance(items, list):
		return items
	return list(items or [])


def _to_float(value: Any) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _normalize_literal(value: Any) -> Any:
	if not isinstance(value, str):
		return value
	trimmed = value.strip()
	if not trimmed:
		return ""
	try:
		return json.loads(trimmed)
	except json.JSONDecodeError:
		return trimmed


def _normalize_field_path(field_path: Any) -> str:
	path = str(field_path or "").strip()
	if path.startswith("header."):
		return path[7:]
	if path.startswith("items."):
		return path[6:]
	if path.startswith("items[]."):
		return path[8:]
	return path


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


def _get_value(obj: Any, fieldname: str, default: Any = None) -> Any:
	if isinstance(obj, dict):
		return obj.get(fieldname, default)
	return getattr(obj, fieldname, default)
