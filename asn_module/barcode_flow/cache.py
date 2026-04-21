from __future__ import annotations

from typing import Any

from frappe.utils import cint

_CONDITION_INDEX_ATTR = "_barcode_flow_condition_index"


def get_enabled_transitions(flow_definition: Any) -> list[Any]:
	"""Return enabled transition rows from a flow definition."""
	return [row for row in (getattr(flow_definition, "transitions", None) or []) if _is_enabled(row)]


def get_condition_by_key(flow_definition: Any, condition_key: str) -> Any | None:
	"""Resolve one condition row by key with a lightweight in-memory cache per flow object."""
	key = (condition_key or "").strip()
	if not key:
		return None

	index = _get_condition_index(flow_definition)
	return index.get(key)


def _get_condition_index(flow_definition: Any) -> dict[str, Any]:
	cached = getattr(flow_definition, _CONDITION_INDEX_ATTR, None)
	if isinstance(cached, dict):
		return cached

	index: dict[str, Any] = {}
	for row in getattr(flow_definition, "conditions", None) or []:
		if not _is_enabled(row):
			continue
		key = (_get_value(row, "condition_key") or "").strip()
		if not key:
			continue
		index[key] = row

	setattr(flow_definition, _CONDITION_INDEX_ATTR, index)
	return index


def _is_enabled(row: Any) -> bool:
	for fieldname in ("enabled", "is_enabled", "is_active"):
		value = _get_value(row, fieldname, None)
		if value is None:
			continue
		return bool(cint(value))
	return True


def _get_value(row: Any, fieldname: str, default: Any = "") -> Any:
	if isinstance(row, dict):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)
