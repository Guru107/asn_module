from __future__ import annotations

from typing import Any

import frappe

from asn_module.barcode_flow.cache import (
	get_cached_condition,
	get_cached_transitions_for_source_node_action,
	get_enabled_transitions,
)
from asn_module.barcode_flow.conditions import evaluate_conditions
from asn_module.barcode_flow.mapping import build_target_doc

_PREGENERATE_MODES = {"immediate", "hybrid"}


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
		contract = _run_custom_handler(
			transition=transition,
			action_binding=action_binding,
			source_doc=source_doc,
			target_doc=None,
		)
		return _attach_generated_scan_codes(
			contract=contract,
			transition=transition,
			flow_definition=flow_definition,
		)

	if binding_mode == "mapping":
		target_doc = _build_mapped_doc(
			transition=transition,
			source_doc=source_doc,
			target_doctype=target_doctype,
			flow_definition=flow_definition,
		)
		target_doc.insert(ignore_permissions=True)
		return _attach_generated_scan_codes(
			contract=_mapped_doc_contract(target_doc),
			transition=transition,
			flow_definition=flow_definition,
			target_doc=target_doc,
		)

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
			contract = _run_custom_handler(
				transition=transition,
				action_binding=action_binding,
				source_doc=source_doc,
				target_doc=target_doc,
			)
			return _attach_generated_scan_codes(
				contract=contract,
				transition=transition,
				flow_definition=flow_definition,
				target_doc=target_doc,
			)

		target_doc = _build_mapped_doc(
			transition=transition,
			source_doc=source_doc,
			target_doctype=target_doctype,
			flow_definition=flow_definition,
		)
		target_doc.insert(ignore_permissions=True)
		return _attach_generated_scan_codes(
			contract=_mapped_doc_contract(target_doc),
			transition=transition,
			flow_definition=flow_definition,
			target_doc=target_doc,
		)

	raise frappe.ValidationError(f"Unsupported binding mode: {binding_mode}")


def _attach_generated_scan_codes(
	*,
	contract: dict,
	transition: Any,
	flow_definition: Any = None,
	target_doc: Any = None,
) -> dict:
	"""Attach pre-generated child scan-code metadata to the runtime contract."""
	result = dict(contract)
	result["generated_scan_codes"] = _generate_child_scan_codes(
		transition=transition,
		flow_definition=flow_definition,
		target_doctype=_get_value(result, "doctype"),
		target_name=_get_value(result, "name"),
		target_doc=target_doc,
	)
	return result


def _generate_child_scan_codes(
	*,
	transition: Any,
	flow_definition: Any = None,
	target_doctype: str = "",
	target_name: str = "",
	target_doc: Any = None,
) -> list[dict]:
	if not flow_definition:
		return []

	flow_name = (_get_value(flow_definition, "name") or _get_value(transition, "flow") or "").strip()
	source_node = (_get_value(transition, "target_node") or "").strip()
	target_doctype = (target_doctype or "").strip()
	target_name = (target_name or "").strip()
	if not flow_name or not source_node or not target_doctype or not target_name:
		return []

	generated: list[dict] = []
	seen_scan_entries: set[tuple[str, str]] = set()
	for child_transition in _get_transitions_for_source_node(
		flow_definition=flow_definition,
		flow=flow_name,
		source_node=source_node,
	):
		generation_mode = (_get_value(child_transition, "generation_mode") or "runtime").strip().lower()
		if generation_mode not in _PREGENERATE_MODES:
			continue

		action_key = _get_action_key(_get_value(child_transition, "action"))
		if not action_key:
			continue

		if not _is_child_transition_condition_met(
			flow_definition=flow_definition,
			child_transition=child_transition,
			target_doctype=target_doctype,
			target_name=target_name,
			target_doc=target_doc,
		):
			continue

		metadata = build_scan_code_metadata(
			action_key=action_key,
			source_doctype=target_doctype,
			source_name=target_name,
			generation_mode=generation_mode,
		)
		dedupe_key = (
			(_get_value(metadata, "action_key") or "").strip(),
			(_get_value(metadata, "scan_code") or "").strip(),
		)
		if dedupe_key in seen_scan_entries:
			continue
		seen_scan_entries.add(dedupe_key)
		generated.append(metadata)

	return generated


def _is_child_transition_condition_met(
	*,
	flow_definition: Any,
	child_transition: Any,
	target_doctype: str,
	target_name: str,
	target_doc: Any = None,
) -> bool:
	condition_name = (_get_value(child_transition, "condition") or "").strip()
	if not condition_name:
		return True

	condition = get_cached_condition(condition_name, cache_holder=flow_definition)
	if not condition:
		transition_key = (_get_value(child_transition, "transition_key") or "<unknown-transition>").strip()
		raise frappe.ValidationError(
			f"Transition {transition_key} references unknown condition: {condition_name}"
		)

	resolved_target_doc = _resolve_target_doc_for_conditions(
		target_doc=target_doc,
		target_doctype=target_doctype,
		target_name=target_name,
	)
	return evaluate_conditions(resolved_target_doc, [condition])


def _get_transitions_for_source_node(*, flow_definition: Any, flow: str, source_node: str) -> list[Any]:
	flow = (flow or "").strip()
	source_node = (source_node or "").strip()
	if not flow or not source_node:
		return []

	# Backward-compatible path for any still-hydrated test fixtures.
	hydrated = [
		row
		for row in get_enabled_transitions(flow_definition)
		if (_get_value(row, "source_node") or "").strip() == source_node
	]
	if hydrated:
		return hydrated

	transition_index: dict[str, Any] = {}
	for action_name in _get_active_action_names():
		for row in get_cached_transitions_for_source_node_action(
			flow_definition,
			flow=flow,
			source_node=source_node,
			action=action_name,
		):
			transition_name = (_get_value(row, "name") or "").strip()
			cache_key = (
				transition_name
				or f"{_get_value(row, 'priority', '')}:{_get_value(row, 'creation', '')}:{_get_value(row, 'transition_key', '')}"
			)
			transition_index[cache_key] = row

	return sorted(
		transition_index.values(),
		key=lambda row: (
			int(_get_value(row, "priority") or 0),
			(_get_value(row, "creation") or ""),
			(_get_value(row, "name") or ""),
		),
	)


def _get_active_action_names() -> list[str]:
	return frappe.get_all(
		"QR Action Definition",
		filters={"is_active": 1},
		pluck="name",
		order_by="name asc",
	)


def _get_action_key(action_link: Any) -> str:
	action_definition = _get_action_definition(action_link)
	if not action_definition:
		return ""
	return (_get_value(action_definition, "action_key") or "").strip()


def _get_action_definition(action_link: Any) -> Any | None:
	if not action_link:
		return None

	if not isinstance(action_link, str):
		return action_link

	try:
		return frappe.get_doc("QR Action Definition", action_link)
	except getattr(frappe, "DoesNotExistError", Exception):
		return None


def _resolve_target_doc_for_conditions(*, target_doc: Any, target_doctype: str, target_name: str) -> Any:
	if _matches_doc_identity(target_doc, target_doctype=target_doctype, target_name=target_name):
		return target_doc
	return frappe.get_doc(target_doctype, target_name)


def _matches_doc_identity(target_doc: Any, *, target_doctype: str, target_name: str) -> bool:
	if not target_doc:
		return False
	return (_get_value(target_doc, "doctype") or "").strip() == target_doctype and (
		_get_value(target_doc, "name") or ""
	).strip() == target_name


def build_scan_code_metadata(
	*, action_key: str, source_doctype: str, source_name: str, generation_mode: str
) -> dict:
	"""Thin wrapper for scan-code metadata helper to keep runtime imports lightweight."""
	from asn_module.qr_engine.generate import build_scan_code_metadata as _build_scan_code_metadata

	return _build_scan_code_metadata(
		action_key=action_key,
		source_doctype=source_doctype,
		source_name=source_name,
		generation_mode=generation_mode,
	)


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

	field_map = _resolve_linked_doc("Barcode Flow Field Map", _get_value(transition, "field_map"))
	if field_map:
		return [field_map]

	return []


def _resolve_action_binding(transition: Any, flow_definition: Any = None, required: bool = False) -> Any:
	hydrated = (
		_get_value(transition, "action_binding")
		or _get_value(transition, "binding")
		or _get_value(transition, "binding_row")
	)
	if hydrated and not isinstance(hydrated, str):
		return hydrated

	linked_action_binding = _resolve_linked_doc("Barcode Flow Action Binding", hydrated)
	if linked_action_binding:
		return linked_action_binding

	if required:
		raise frappe.ValidationError("Action Binding link is required for custom handler transition binding")
	return None


def _resolve_linked_doc(doctype: str, value: Any) -> Any | None:
	if not value:
		return None

	if not isinstance(value, str):
		return value

	try:
		return frappe.get_doc(doctype, value)
	except getattr(frappe, "DoesNotExistError", Exception):
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
	source_doctype = (
		_get_value(source_doc, "doctype") or _get_value(source_doc, "source_doctype") or ""
	).strip()
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
