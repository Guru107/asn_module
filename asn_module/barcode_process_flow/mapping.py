from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def build_target_doc(source_doc: Any, mapping_rows: list[Any], target_doctype: str):
	payload: dict[str, Any] = {"doctype": target_doctype}
	source_doctype = (getattr(source_doc, "doctype", "") or "").strip()
	selector_cache: dict[tuple[str, str, str], str] = {}
	prepared_rows = _prepare_mapping_rows(
		source_doctype=source_doctype,
		target_doctype=target_doctype,
		mapping_rows=mapping_rows,
		selector_cache=selector_cache,
	)

	header_rows = [row for row in prepared_rows if not row["target_selector"].startswith("items[].")]
	item_rows = [row for row in prepared_rows if row["target_selector"].startswith("items[].")]

	for prepared in header_rows:
		target_path = _normalize_target_selector(prepared["target_selector"])
		value = _resolve_row_value(
			row=prepared["row"],
			source_doc=source_doc,
			source_item=None,
			source_selector=prepared.get("source_selector", ""),
		)
		_set_dotted(payload, target_path, value)

	if item_rows:
		payload["items"] = _build_target_items(source_doc=source_doc, item_rows=item_rows)

	return frappe.get_doc(payload)


def _prepare_mapping_rows(
	*,
	source_doctype: str,
	target_doctype: str,
	mapping_rows: list[Any],
	selector_cache: dict[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
	prepared: list[dict[str, Any]] = []
	for row in mapping_rows or []:
		target_selector = _selector_from_docfield_reference(
			docfield_reference=_get_value(row, "target_field"),
			parent_doctype=target_doctype,
			side="target",
			selector_cache=selector_cache,
		)
		if not target_selector:
			raise frappe.ValidationError(
				_("Target Field is required and must belong to {0} or its items table").format(
					target_doctype or _("Target DocType"),
				)
			)

		mapping_type = (_get_value(row, "mapping_type") or "source").strip().lower()
		source_selector = ""
		if mapping_type == "source":
			source_selector = _selector_from_docfield_reference(
				docfield_reference=_get_value(row, "source_field"),
				parent_doctype=source_doctype,
				side="source",
				selector_cache=selector_cache,
			)
			if not source_selector:
				raise frappe.ValidationError(
					_("Source Field is required and must belong to {0} or its items table").format(
						source_doctype or _("Source DocType"),
					)
				)

		prepared.append(
			{
				"row": row,
				"target_selector": target_selector,
				"source_selector": source_selector,
			}
		)
	return prepared


def _build_target_items(*, source_doc: Any, item_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	source_items = list(_get_value(source_doc, "items", []) or [])
	if not source_items:
		return []

	target_items: list[dict[str, Any]] = []
	for source_item in source_items:
		target_item: dict[str, Any] = {}
		for prepared in item_rows:
			target_path = _normalize_target_selector(prepared["target_selector"])
			target_path = target_path[8:] if target_path.startswith("items[].") else target_path
			value = _resolve_row_value(
				row=prepared["row"],
				source_doc=source_doc,
				source_item=source_item,
				source_selector=prepared.get("source_selector", ""),
			)
			_set_dotted(target_item, target_path, value)
		if target_item:
			target_items.append(target_item)
	return target_items


def _resolve_row_value(
	*,
	row: Any,
	source_doc: Any,
	source_item: Any = None,
	source_selector: str = "",
) -> Any:
	mapping_type = (_get_value(row, "mapping_type") or "source").strip().lower()
	if mapping_type == "constant":
		value = _get_value(row, "constant_value")
	else:
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


def _selector_from_docfield_reference(
	*,
	docfield_reference: Any,
	parent_doctype: str,
	side: str,
	selector_cache: dict[tuple[str, str, str], str],
) -> str:
	docfield_key = str(docfield_reference or "").strip()
	normalized_parent = (parent_doctype or "").strip()
	normalized_side = (side or "").strip().lower()
	if not docfield_key or not normalized_parent or normalized_side not in {"source", "target"}:
		return ""

	cache_key = (docfield_key, normalized_parent, normalized_side)
	if cache_key in selector_cache:
		return selector_cache[cache_key]

	field_parent, fieldname = _resolve_docfield_reference(docfield_key)
	if not field_parent or not fieldname:
		selector_cache[cache_key] = ""
		return ""

	if field_parent == normalized_parent:
		selector = f"header.{fieldname}" if normalized_side == "source" else fieldname
		selector_cache[cache_key] = selector
		return selector

	items_doctype = _get_items_child_doctype(normalized_parent)
	if items_doctype and field_parent == items_doctype:
		selector_cache[cache_key] = f"items[].{fieldname}"
		return selector_cache[cache_key]

	selector_cache[cache_key] = ""
	return ""


def _resolve_docfield_reference(reference: str) -> tuple[str, str]:
	reference = (reference or "").strip()
	if not reference:
		return "", ""
	if "." in reference:
		field_parent, fieldname = [part.strip() for part in reference.split(".", 1)]
		return field_parent, fieldname

	row = frappe.db.get_value("DocField", reference, ["parent", "fieldname"], as_dict=True)
	if not row:
		return "", ""
	return (row.get("parent") or "").strip(), (row.get("fieldname") or "").strip()


def _get_items_child_doctype(parent_doctype: str) -> str:
	parent_doctype = (parent_doctype or "").strip()
	if not parent_doctype:
		return ""

	meta = frappe.get_meta(parent_doctype)
	for field in list(meta.fields or []):
		fieldtype = (field.fieldtype or "").strip()
		if fieldtype not in {"Table", "Table MultiSelect"}:
			continue
		if (field.fieldname or "").strip() != "items":
			continue
		return (field.options or "").strip()
	return ""


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
