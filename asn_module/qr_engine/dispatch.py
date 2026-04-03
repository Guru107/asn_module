import frappe

from asn_module.qr_engine.token import verify_token


class ActionNotFoundError(frappe.ValidationError):
	pass


class PermissionDeniedError(frappe.PermissionError):
	pass


def _resolve_action(action_key: str) -> dict:
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
		}
	).insert(ignore_permissions=True)


def _call_handler(handler_method: str, source_doctype: str, source_name: str, payload: dict) -> dict:
	module_path, method_name = handler_method.rsplit(".", 1)
	module = frappe.get_module(module_path)
	handler_fn = getattr(module, method_name)
	return handler_fn(source_doctype=source_doctype, source_name=source_name, payload=payload)


@frappe.whitelist(allow_guest=False)
def dispatch(token: str, device_info: str = "Desktop") -> dict:
	payload = None
	action_key = "unknown"
	source_doctype = "DocType"
	source_name = "QR Action Registry"

	try:
		payload = {**verify_token(token), "device_info": device_info}
		action_key = payload["action"]
		source_doctype = payload["source_doctype"]
		source_name = payload["source_name"]

		action = _resolve_action(action_key)
		_validate_source_doctype(action["source_doctype"], source_doctype)
		_check_permission(action["allowed_roles"])

		handler_result = _validate_handler_result(
			_call_handler(action["handler"], source_doctype, source_name, payload)
		)

		# Handlers that return Scan Log already persist the success audit row; avoid a second log.
		if handler_result.get("doctype") != "Scan Log":
			_log_scan(
				action=action_key,
				source_doctype=source_doctype,
				source_name=source_name,
				result="Success",
				device_info=device_info,
				result_doctype=handler_result.get("doctype"),
				result_name=handler_result.get("name"),
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
		)
		frappe.db.commit()
		raise
