from __future__ import annotations

from typing import Any

import frappe


def build_target_doc(source_doc: Any, mapping_rows: list[Any], target_doctype: str):
	payload: dict[str, Any] = {"doctype": target_doctype}
	header_rows: list[Any] = []
	item_rows: list[Any] = []

	for row in mapping_rows or []:
		target = (_get_value(row, "target_selector") or "").strip()
		if not target:
			continue
		if target.startswith("items[]."):
			item_rows.append(row)
		else:
			header_rows.append(row)

	for row in header_rows:
		target_path = _normalize_target_selector(_get_value(row, "target_selector"))
		value = _resolve_row_value(row=row, source_doc=source_doc, source_item=None)
		_set_dotted(payload, target_path, value)

	if item_rows:
		payload["items"] = _build_target_items(source_doc=source_doc, item_rows=item_rows)

	return frappe.get_doc(payload)


def _build_target_items(*, source_doc: Any, item_rows: list[Any]) -> list[dict[str, Any]]:
	source_items = list(_get_value(source_doc, "items", []) or [])
	if not source_items:
		return []

	target_items: list[dict[str, Any]] = []
	for source_item in source_items:
		target_item: dict[str, Any] = {}
		for row in item_rows:
			target_path = _normalize_target_selector(_get_value(row, "target_selector"))
			target_path = target_path[8:] if target_path.startswith("items[].") else target_path
			value = _resolve_row_value(row=row, source_doc=source_doc, source_item=source_item)
			_set_dotted(target_item, target_path, value)
		if target_item:
			target_items.append(target_item)
	return target_items


def _resolve_row_value(*, row: Any, source_doc: Any, source_item: Any = None) -> Any:
	mapping_type = (_get_value(row, "mapping_type") or "source").strip().lower()
	if mapping_type == "constant":
		value = _get_value(row, "constant_value")
	else:
		source_selector = (_get_value(row, "source_selector") or "").strip()
		value = _resolve_source_selector(
			source_doc=source_doc, source_item=source_item, selector=source_selector
		)
	return _apply_transform(value, (_get_value(row, "transform") or "").strip().lower())


def _resolve_source_selector(*, source_doc: Any, source_item: Any, selector: str) -> Any:
	if not selector:
		return None

	path = selector.strip()
	if path.startswith("header."):
		return _resolve_dotted(source_doc, path[7:])
	if path.startswith("items[]."):
		if source_item is None:
			return None
		return _resolve_dotted(source_item, path[8:])
	return _resolve_dotted(source_doc, path)


def _normalize_target_selector(target_selector: str | None) -> str:
	target = (target_selector or "").strip()
	if target.startswith("target."):
		return target[7:]
	return target


def _apply_transform(value: Any, transform: str) -> Any:
	if not transform:
		return value
	if transform == "upper":
		return str(value).upper() if value is not None else value
	if transform == "lower":
		return str(value).lower() if value is not None else value
	if transform == "int":
		return int(value) if value not in (None, "") else None
	if transform == "float":
		return float(value) if value not in (None, "") else None
	if transform == "str":
		return "" if value is None else str(value)
	return value


def _resolve_dotted(source: Any, path: str) -> Any:
	current = source
	for segment in [part.strip() for part in path.split(".") if part.strip()]:
		if current is None:
			return None
		if isinstance(current, dict):
			if segment not in current:
				return None
			current = current.get(segment)
			continue
		if hasattr(current, segment):
			current = getattr(current, segment)
			continue
		getter = getattr(current, "get", None)
		if callable(getter):
			current = getter(segment)
			continue
		return None
	return current


def _set_dotted(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
	segments = [part.strip() for part in dotted_path.split(".") if part.strip()]
	if not segments:
		return
	if len(segments) == 1:
		payload[segments[0]] = value
		return

	current = payload
	for segment in segments[:-1]:
		next_value = current.get(segment)
		if not isinstance(next_value, dict):
			next_value = {}
			current[segment] = next_value
		current = next_value
	current[segments[-1]] = value


def _get_value(obj: Any, fieldname: str, default: Any = None) -> Any:
	if isinstance(obj, dict):
		return obj.get(fieldname, default)
	return getattr(obj, fieldname, default)
