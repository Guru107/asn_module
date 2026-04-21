from __future__ import annotations

from typing import Any

import frappe


def build_target_doc(source_doc: Any, mappings: list[Any] | tuple[Any, ...] | None, target_doctype: str):
	"""Build a target document from source data and field-map rows."""
	payload: dict[str, Any] = {"doctype": target_doctype}

	for row in mappings or []:
		mapping_type = (_get_value(row, "mapping_type") or "").strip().lower()
		target_field_path = (_get_value(row, "target_field_path") or "").strip()
		if not target_field_path:
			continue

		if mapping_type == "source":
			source_field_path = (_get_value(row, "source_field_path") or "").strip()
			if not source_field_path:
				raise frappe.ValidationError("Source field path is required for source mapping type")
			value = _resolve_source_value(source_doc, source_field_path)
		elif mapping_type == "constant":
			value = _get_value(row, "constant_value")
		else:
			raise frappe.ValidationError(f"Unsupported mapping type: {mapping_type}")

		_set_dotted_path(payload, _normalize_target_path(target_field_path), value)

	return frappe.get_doc(payload)


def _resolve_source_value(source_doc: Any, source_field_path: str) -> Any:
	normalized = source_field_path.strip()
	if not normalized:
		return None

	value = _resolve_dotted_path(source_doc, normalized)
	if value is not None:
		return value

	# Support legacy "header.<field>" mappings where "header" points to source root.
	if normalized.startswith("header."):
		return _resolve_dotted_path(source_doc, normalized[len("header.") :])

	return value


def _resolve_dotted_path(source: Any, dotted_path: str) -> Any:
	current = source
	if not dotted_path:
		return current

	for segment in dotted_path.split("."):
		segment = segment.strip()
		if not segment:
			continue

		if current is None:
			return None

		if isinstance(current, dict):
			if segment not in current:
				return None
			current = current.get(segment)
			continue

		if not hasattr(current, segment):
			return None
		current = getattr(current, segment)

	return current


def _set_dotted_path(target: dict[str, Any], dotted_path: str, value: Any) -> None:
	if not dotted_path:
		return

	segments = [part.strip() for part in dotted_path.split(".") if part.strip()]
	if not segments:
		return

	if len(segments) == 1:
		target[segments[0]] = value
		return

	current: dict[str, Any] = target
	for segment in segments[:-1]:
		next_value = current.get(segment)
		if not isinstance(next_value, dict):
			next_value = {}
			current[segment] = next_value
		current = next_value

	current[segments[-1]] = value


def _normalize_target_path(path: str) -> str:
	normalized = path.strip()
	if normalized.startswith("target."):
		return normalized[len("target.") :]
	return normalized


def _get_value(row: Any, fieldname: str, default: Any = "") -> Any:
	if isinstance(row, dict):
		return row.get(fieldname, default)

	return getattr(row, fieldname, default)
