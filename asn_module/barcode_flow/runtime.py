from __future__ import annotations

from typing import Any

import frappe

from asn_module.barcode_flow.mapping import build_target_doc


def execute_transition_binding(transition: Any, source_doc: Any, flow_definition: Any = None) -> dict:
	"""Execute binding logic for one transition and return dispatch contract."""
	binding_mode = (_get_value(transition, "binding_mode") or "mapping").strip()
	action_binding = _resolve_action_binding(
		transition,
		flow_definition=flow_definition,
		required=binding_mode in {"custom_handler", "both"},
	)
	target_doctype = _resolve_target_doctype(transition)

	if binding_mode == "custom_handler":
		return _run_custom_handler(
			transition=transition,
			action_binding=action_binding,
			source_doc=source_doc,
			target_doc=None,
		)

	if binding_mode == "mapping":
		target_doc = _build_mapped_doc(
			transition=transition,
			source_doc=source_doc,
			target_doctype=target_doctype,
			flow_definition=flow_definition,
		)
		target_doc.insert(ignore_permissions=True)
		return _mapped_doc_contract(target_doc)

	if binding_mode == "both":
		override_wins = _as_bool(_get_value(action_binding, "handler_override_wins", 0))
		if override_wins:
			target_doc = None
			if target_doctype:
				target_doc = _build_mapped_doc(
					transition=transition,
					source_doc=source_doc,
					target_doctype=target_doctype,
					flow_definition=flow_definition,
				)
			return _run_custom_handler(
				transition=transition,
				action_binding=action_binding,
				source_doc=source_doc,
				target_doc=target_doc,
			)

		target_doc = _build_mapped_doc(
			transition=transition,
			source_doc=source_doc,
			target_doctype=target_doctype,
			flow_definition=flow_definition,
		)
		target_doc.insert(ignore_permissions=True)
		return _mapped_doc_contract(target_doc)

	raise frappe.ValidationError(f"Unsupported binding mode: {binding_mode}")


def _build_mapped_doc(
	transition: Any,
	source_doc: Any,
	target_doctype: str,
	flow_definition: Any,
) -> Any:
	if not target_doctype:
		raise frappe.ValidationError("Target doctype is required for mapping-based transition binding")

	mappings = _resolve_field_maps(transition, flow_definition=flow_definition)
	return build_target_doc(
		source_doc=source_doc,
		mappings=mappings,
		target_doctype=target_doctype,
	)


def _resolve_field_maps(transition: Any, flow_definition: Any = None) -> list[Any]:
	hydrated = _get_value(transition, "field_maps")
	if hydrated:
		return list(hydrated)

	map_key = (_get_value(transition, "field_map_key") or "").strip()
	if not map_key:
		return []

	if not flow_definition:
		raise frappe.ValidationError(
			f"Field map key {map_key} requires flow definition context for resolution"
		)

	field_maps = _get_value(flow_definition, "field_maps") or []
	for row in field_maps:
		if (_get_value(row, "map_key") or "").strip() == map_key:
			return [row]

	raise frappe.ValidationError(f"Unknown field map key on transition: {map_key}")


def _resolve_action_binding(transition: Any, flow_definition: Any = None, required: bool = False) -> Any:
	hydrated = (
		_get_value(transition, "action_binding")
		or _get_value(transition, "binding")
		or _get_value(transition, "binding_row")
	)
	if hydrated:
		return hydrated

	binding_key = (_get_value(transition, "binding_key") or "").strip()
	if not binding_key:
		if required:
			raise frappe.ValidationError("Binding key is required for custom handler transition binding")
		return None

	if not flow_definition:
		raise frappe.ValidationError(
			f"Binding key {binding_key} requires flow definition context for resolution"
		)

	bindings = _get_value(flow_definition, "action_bindings") or []
	for row in bindings:
		if (_get_value(row, "binding_key") or "").strip() == binding_key:
			return row

	raise frappe.ValidationError(f"Unknown binding key on transition: {binding_key}")


def _run_custom_handler(
	*,
	transition: Any,
	action_binding: Any,
	source_doc: Any,
	target_doc: Any,
) -> dict:
	handler_path = (
		(_get_value(action_binding, "custom_handler") if action_binding else "")
		or _get_value(transition, "custom_handler")
		or ""
	).strip()
	if not handler_path:
		raise frappe.ValidationError("Custom handler path is required for custom handler transition binding")

	handler_fn = frappe.get_attr(handler_path)
	source_doctype, source_name = _source_identity(source_doc)
	handler_result = handler_fn(
		source_doctype=source_doctype,
		source_name=source_name,
		payload={
			"transition": transition,
			"action_binding": action_binding,
			"target_doc": target_doc,
			"source_doc": source_doc,
		},
	)
	return _validate_handler_result(handler_result)


def _source_identity(source_doc: Any) -> tuple[str, str]:
	source_doctype = (_get_value(source_doc, "doctype") or _get_value(source_doc, "source_doctype") or "").strip()
	source_name = (_get_value(source_doc, "name") or _get_value(source_doc, "source_name") or "").strip()
	return source_doctype, source_name


def _validate_handler_result(handler_result: object) -> dict:
	if not isinstance(handler_result, dict):
		raise frappe.ValidationError("Invalid handler result: expected a dict")

	required_keys = ("doctype", "name", "url")
	missing_keys = [key for key in required_keys if not handler_result.get(key)]
	if missing_keys:
		raise frappe.ValidationError(f"Invalid handler result: missing {', '.join(missing_keys)}")

	return handler_result


def _mapped_doc_contract(target_doc: Any) -> dict:
	doctype = _get_value(target_doc, "doctype")
	name = _get_value(target_doc, "name")
	url = _extract_doc_url(target_doc)

	if not doctype or not name or not url:
		raise frappe.ValidationError("Invalid mapped target result: doctype, name and url are required")

	return {"doctype": doctype, "name": name, "url": url}


def _extract_doc_url(doc: Any) -> str:
	get_url = getattr(doc, "get_url", None)
	if callable(get_url):
		return get_url() or ""

	return _get_value(doc, "url") or ""


def _resolve_target_doctype(transition: Any) -> str:
	return (_get_value(transition, "target_doctype") or "").strip()


def _as_bool(value: Any) -> bool:
	if isinstance(value, str):
		value = value.strip()
		if not value:
			return False
		if value.lower() in {"true", "yes"}:
			return True

	try:
		return bool(int(value))
	except (TypeError, ValueError):
		return bool(value)


def _get_value(row: Any, fieldname: str, default: Any = "") -> Any:
	if row is None:
		return default
	if isinstance(row, dict):
		return row.get(fieldname, default)

	return getattr(row, fieldname, default)
