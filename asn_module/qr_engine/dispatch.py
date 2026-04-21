import frappe
from frappe import _
from frappe.utils import cint

from asn_module.barcode_flow.cache import get_condition_by_key, get_enabled_transitions
from asn_module.barcode_flow.conditions import evaluate_conditions
from asn_module.barcode_flow.resolver import resolve_flow_with_scope
from asn_module.barcode_flow.runtime import execute_transition_binding
from asn_module.qr_engine.scan_codes import (
	get_scan_code_doc,
	normalize_scan_code,
	record_successful_scan,
	validate_scan_code_row,
)


class ActionNotFoundError(frappe.ValidationError):
	pass


class PermissionDeniedError(frappe.PermissionError):
	pass


class ScanCodeNotFoundError(frappe.ValidationError):
	pass


class TransitionResolutionError(frappe.ValidationError):
	pass


def _resolve_action(action_key: str) -> dict:
	registry = frappe.get_single("QR Action Registry")
	action = registry.get_action(action_key)
	if not action:
		# Self-heal: re-apply canonical action registry when singleton rows are stale.
		from asn_module.setup_actions import register_actions

		register_actions()
		registry = frappe.get_single("QR Action Registry")
		action = registry.get_action(action_key)
		if not action:
			raise ActionNotFoundError(f"Unknown QR action: {action_key}")

	return {
		"handler": action["handler_method"],
		"source_doctype": action["source_doctype"],
		"allowed_roles": action["allowed_roles"],
	}


def _check_permission(allowed_roles: list[str]) -> None:
	user_roles = frappe.get_roles()
	if any(role in user_roles for role in allowed_roles):
		return

	raise PermissionDeniedError(
		f"You do not have permission to perform this action. Required roles: {', '.join(allowed_roles)}"
	)


def _validate_source_doctype(expected_source_doctype: str, actual_source_doctype: str) -> None:
	if expected_source_doctype == actual_source_doctype:
		return

	raise ActionNotFoundError(
		f"QR action source doctype mismatch: expected {expected_source_doctype}, got {actual_source_doctype}"
	)


def _validate_handler_result(handler_result: object) -> dict:
	if not isinstance(handler_result, dict):
		raise frappe.ValidationError("Invalid handler result: expected a dict")

	required_keys = ("doctype", "name", "url")
	missing_keys = [key for key in required_keys if not handler_result.get(key)]
	if missing_keys:
		raise frappe.ValidationError(f"Invalid handler result: missing {', '.join(missing_keys)}")

	return handler_result


def _get_failure_log_identity(source_doctype: str | None, source_name: str | None) -> tuple[str, str]:
	try:
		if source_doctype and source_name and frappe.db.exists("DocType", source_doctype):
			if frappe.db.exists(source_doctype, source_name):
				return source_doctype, source_name
	except Exception:
		pass

	return "DocType", "QR Action Registry"


def _log_scan(
	*,
	action: str,
	source_doctype: str,
	source_name: str,
	result: str,
	device_info: str,
	result_doctype: str | None = None,
	result_name: str | None = None,
	error_message: str | None = None,
	barcode_flow_definition: str | None = None,
	barcode_flow_transition: str | None = None,
	scope_resolution_key: str | None = None,
) -> None:
	frappe.get_doc(
		{
			"doctype": "Scan Log",
			"action": action,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"device_info": device_info,
			"result": result,
			"result_doctype": result_doctype,
			"result_name": result_name,
			"error_message": error_message,
			"barcode_flow_definition": barcode_flow_definition,
			"barcode_flow_transition": barcode_flow_transition,
			"scope_resolution_key": scope_resolution_key,
		}
	).insert(ignore_permissions=True)


def _build_flow_resolution_context(source_doc: frappe.model.document.Document) -> dict:
	return {
		"source_doctype": _normalize_value(_get_value(source_doc, "doctype")),
		"company": _normalize_value(_get_value(source_doc, "company")),
		"warehouse": _normalize_value(
			_get_value(source_doc, "warehouse") or _get_value(source_doc, "set_warehouse")
		),
		"supplier_type": _normalize_value(_resolve_supplier_type(source_doc)),
	}


def _resolve_supplier_type(source_doc: frappe.model.document.Document) -> str | None:
	supplier_type = _normalize_value(_get_value(source_doc, "supplier_type"))
	if supplier_type:
		return supplier_type

	supplier = _normalize_value(_get_value(source_doc, "supplier"))
	if not supplier:
		return None

	return _normalize_value(frappe.db.get_value("Supplier", supplier, "supplier_type"))


def _resolve_matching_transition(
	flow_definition: frappe.model.document.Document,
	action_key: str,
	source_doc: frappe.model.document.Document,
) -> frappe.model.document.Document:
	matching: list[frappe.model.document.Document] = []

	for transition in get_enabled_transitions(flow_definition):
		if _normalize_value(_get_value(transition, "action_key")) != action_key:
			continue

		condition_key = _normalize_value(_get_value(transition, "condition_key"))
		if condition_key:
			condition = get_condition_by_key(flow_definition, condition_key)
			if not condition:
				transition_key = _normalize_value(_get_value(transition, "transition_key")) or "<unknown-transition>"
				raise TransitionResolutionError(
					f"Transition {transition_key} references unknown condition key: {condition_key}"
				)
			if not evaluate_conditions(source_doc, [condition]):
				continue

		matching.append(transition)

	if not matching:
		raise TransitionResolutionError(
			f"No enabled barcode transition matched action '{action_key}' in flow '{flow_definition.name}'"
		)

	top_priority = max(_transition_priority(transition) for transition in matching)
	winners = [transition for transition in matching if _transition_priority(transition) == top_priority]
	if len(winners) > 1:
		transition_keys = ", ".join(
			sorted(
				_normalize_value(_get_value(transition, "transition_key")) or "<unknown-transition>"
				for transition in winners
			)
		)
		raise TransitionResolutionError(
			f"Ambiguous barcode transition resolution in flow '{flow_definition.name}' for action '{action_key}'. "
			f"Matching transitions: {transition_keys}"
		)

	return winners[0]


def _transition_priority(transition: frappe.model.document.Document) -> int:
	return cint(_get_value(transition, "priority") or 0)


def _get_value(row: object, fieldname: str, default: object = None) -> object:
	if isinstance(row, dict):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)


def _normalize_value(value: object) -> str | None:
	if value is None:
		return None
	if isinstance(value, str):
		trimmed = value.strip()
		return trimmed or None
	return str(value)


@frappe.whitelist(allow_guest=False)
def dispatch(code: str | None = None, device_info: str = "Desktop") -> dict:
	"""Resolve a short scan ``code`` (URL param or raw) and execute a configured flow transition."""
	if not code:
		code = frappe.form_dict.get("code")

	raw_input = (code or "").strip()
	normalized = normalize_scan_code(raw_input)

	action_key = "unknown"
	source_doctype = "DocType"
	source_name = "QR Action Registry"
	barcode_flow_definition = None
	barcode_flow_transition = None
	scope_resolution_key = None

	try:
		if not normalized:
			if raw_input:
				raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))
			raise ScanCodeNotFoundError(_("Missing scan code."))

		scan_doc = get_scan_code_doc(normalized)
		if not scan_doc:
			raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))

		action_key = scan_doc.action_key
		source_doctype = scan_doc.source_doctype
		source_name = scan_doc.source_name

		validate_scan_code_row(scan_doc, action_key)

		action = _resolve_action(action_key)
		_validate_source_doctype(action["source_doctype"], source_doctype)
		_check_permission(action["allowed_roles"])

		source_doc = frappe.get_doc(source_doctype, source_name)
		flow_context = _build_flow_resolution_context(source_doc)
		flow_definition, scope_resolution_key = resolve_flow_with_scope(flow_context)
		transition = _resolve_matching_transition(flow_definition, action_key, source_doc)

		barcode_flow_definition = flow_definition.name
		barcode_flow_transition = _normalize_value(_get_value(transition, "transition_key"))

		handler_result = _validate_handler_result(
			execute_transition_binding(
				transition=transition,
				source_doc=source_doc,
				flow_definition=flow_definition,
			)
		)

		record_successful_scan(scan_doc.name, action_key)

		if handler_result.get("doctype") != "Scan Log":
			_log_scan(
				action=action_key,
				source_doctype=source_doctype,
				source_name=source_name,
				result="Success",
				device_info=device_info,
				result_doctype=handler_result.get("doctype"),
				result_name=handler_result.get("name"),
				barcode_flow_definition=barcode_flow_definition,
				barcode_flow_transition=barcode_flow_transition,
				scope_resolution_key=scope_resolution_key,
			)
		frappe.local.flags.commit = True

		return {
			"success": True,
			"action": action_key,
			"doctype": handler_result["doctype"],
			"name": handler_result["name"],
			"url": handler_result["url"],
			"message": handler_result.get("message", ""),
		}
	except Exception as exc:
		failure_source_doctype, failure_source_name = _get_failure_log_identity(source_doctype, source_name)
		_log_scan(
			action=action_key,
			source_doctype=failure_source_doctype,
			source_name=failure_source_name,
			result="Failure",
			device_info=device_info,
			error_message=str(exc),
			barcode_flow_definition=barcode_flow_definition,
			barcode_flow_transition=barcode_flow_transition,
			scope_resolution_key=scope_resolution_key,
		)
		frappe.db.commit()
		raise
