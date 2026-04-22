from __future__ import annotations

from typing import Any

from frappe.utils import cint

from asn_module.barcode_flow import repository

_CONDITION_INDEX_ATTR = "_barcode_flow_condition_index"
_RELATIONAL_CONDITION_CACHE_ATTR = "_barcode_flow_relational_condition_cache"
_RELATIONAL_TRANSITION_CACHE_ATTR = "_barcode_flow_relational_transition_cache"


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


def get_cached_transitions_for_source_node_action(
	cache_holder: Any, *, flow: str, source_node: str, action: str
) -> list[Any]:
	cache = _get_relational_transition_cache(cache_holder)
	cache_key = ((flow or "").strip(), (source_node or "").strip(), (action or "").strip())
	if cache_key not in cache:
		cache[cache_key] = repository.get_transitions_for_source_node_action(
			flow=cache_key[0],
			source_node=cache_key[1],
			action=cache_key[2],
		)
	return cache[cache_key]


def get_cached_condition(condition_name: str, *, cache_holder: Any | None = None) -> Any | None:
	name = (condition_name or "").strip()
	if not name:
		return None
	if cache_holder is None:
		return repository.get_condition(name)

	cache = _get_relational_condition_cache(cache_holder)
	if name not in cache:
		cache[name] = repository.get_condition(name)
	return cache[name]


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


def _get_relational_transition_cache(cache_holder: Any) -> dict[tuple[str, str, str], list[Any]]:
	cached = getattr(cache_holder, _RELATIONAL_TRANSITION_CACHE_ATTR, None)
	if isinstance(cached, dict):
		return cached

	cache: dict[tuple[str, str, str], list[Any]] = {}
	setattr(cache_holder, _RELATIONAL_TRANSITION_CACHE_ATTR, cache)
	return cache


def _get_relational_condition_cache(cache_holder: Any) -> dict[str, Any | None]:
	cached = getattr(cache_holder, _RELATIONAL_CONDITION_CACHE_ATTR, None)
	if isinstance(cached, dict):
		return cached

	cache: dict[str, Any | None] = {}
	setattr(cache_holder, _RELATIONAL_CONDITION_CACHE_ATTR, cache)
	return cache


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
