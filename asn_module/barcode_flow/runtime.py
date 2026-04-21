from __future__ import annotations

from typing import Any

import frappe

from asn_module.barcode_flow.mapping import build_target_doc


def execute_transition_binding(transition: Any, source_doc: Any) -> dict:
	"""Execute binding logic for one transition and return dispatch contract."""
	binding_mode = (_get_value(transition, "binding_mode") or "mapping").strip()
	action_binding = _resolve_action_binding(transition)
	target_doctype = _resolve_target_doctype(transition, action_binding)

	if binding_mode == "custom_handler":
		return _run_custom_handler(
			transition=transition,
			action_binding=action_binding,
			source_doc=source_doc,
			target_doc=None,
		)

	if binding_mode == "mapping":
		target_doc = _build_mapped_doc(transition=transition, source_doc=source_doc, target_doctype=target_doctype)
		target_doc.insert(ignore_permissions=True)
		return _mapped_doc_contract(target_doc)

	if binding_mode == "both":
		override_wins = _as_bool(_get_value(action_binding, "handler_override_wins", 0))
		if override_wins:
			target_doc = _try_build_mapped_doc(
				transition=transition,
				source_doc=source_doc,
				target_doctype=target_doctype,
			)
			return _run_custom_handler(
				transition=transition,
				action_binding=action_binding,
				source_doc=source_doc,
				target_doc=target_doc,
			)

		target_doc = _build_mapped_doc(transition=transition, source_doc=source_doc, target_doctype=target_doctype)
		target_doc.insert(ignore_permissions=True)
		return _mapped_doc_contract(target_doc)

	raise frappe.ValidationError(f"Unsupported binding mode: {binding_mode}")


def _build_mapped_doc(transition: Any, source_doc: Any, target_doctype: str) -> Any:
	if not target_doctype:
		raise frappe.ValidationError("Target doctype is required for mapping-based transition binding")

	return build_target_doc(
		source_doc=source_doc,
		mappings=_get_value(transition, "field_maps") or [],
		target_doctype=target_doctype,
	)


def _try_build_mapped_doc(transition: Any, source_doc: Any, target_doctype: str) -> Any | None:
	try:
		return _build_mapped_doc(
			transition=transition,
			source_doc=source_doc,
			target_doctype=target_doctype,
		)
	except frappe.ValidationError:
		return None


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
	handler_result = handler_fn(
		source_doc=source_doc,
		transition=transition,
		action_binding=action_binding,
		target_doc=target_doc,
	)
	return _validate_handler_result(handler_result)


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


def _resolve_action_binding(transition: Any) -> Any:
	return (
		_get_value(transition, "action_binding")
		or _get_value(transition, "binding")
		or _get_value(transition, "binding_row")
	)


def _resolve_target_doctype(transition: Any, action_binding: Any) -> str:
	return (
		(_get_value(transition, "target_doctype") or "").strip()
		or (_get_value(action_binding, "target_doctype") or "").strip()
	)


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
