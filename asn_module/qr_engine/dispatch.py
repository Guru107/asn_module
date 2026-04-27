import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from asn_module.qr_engine.scan_codes import (
	RESCAN_SAFE_ACTIONS,
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
	scan_code: str | None = None,
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
			"scan_code": scan_code,
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


def _get_existing_success_result(
	action_key: str,
	source_doctype: str,
	source_name: str,
	scan_code: str,
) -> dict | None:
	logs = frappe.get_all(
		"Scan Log",
		filters={
			"action": action_key,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"scan_code": scan_code,
			"result": "Success",
			"result_doctype": ("is", "set"),
			"result_name": ("is", "set"),
		},
		fields=["result_doctype", "result_name"],
		order_by="creation desc",
		limit=5,
	)
	for log in logs:
		try:
			if not frappe.db.exists(log["result_doctype"], log["result_name"]):
				continue
			doc = frappe.get_doc(log["result_doctype"], log["result_name"])
		except (frappe.DoesNotExistError, frappe.PermissionError, ImportError):
			continue
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				_("Failed to resolve existing result from Scan Log"),
			)
			raise
		return {
			"doctype": doc.doctype,
			"name": doc.name,
			"url": doc.get_url(),
			"message": _("Existing {0} {1} opened").format(doc.doctype, doc.name),
		}
	return None


def _can_open_existing_result(scan_doc: frappe.model.document.Document, action_key: str) -> bool:
	if scan_doc.status != "Used" or action_key in RESCAN_SAFE_ACTIONS:
		return False
	if scan_doc.expires_on and get_datetime(scan_doc.expires_on) < now_datetime():
		return False
	return True


def _payload_from_scan_code_registry(scan_doc: frappe.model.document.Document, device_info: str) -> dict:
	return {
		"action": scan_doc.action_key,
		"source_doctype": scan_doc.source_doctype,
		"source_name": scan_doc.source_name,
		"created_at": str(scan_doc.generated_on or ""),
		"created_by": scan_doc.generated_by or "",
		"device_info": device_info,
		"scan_code": scan_doc.name,
	}


@frappe.whitelist(allow_guest=False)
def dispatch(code: str | None = None, device_info: str = "Desktop") -> dict:
	"""Resolve a short scan ``code`` (URL param or raw) and run the registered handler."""
	if not code:
		code = frappe.form_dict.get("code")

	raw_input = (code or "").strip()
	normalized = normalize_scan_code(raw_input)

	action_key = "unknown"
	source_doctype = "DocType"
	source_name = "QR Action Registry"
	scan_code_name = None

	try:
		if not normalized:
			if raw_input:
				raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))
			raise ScanCodeNotFoundError(_("Missing scan code."))

		scan_doc = get_scan_code_doc(normalized)
		if not scan_doc:
			raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))

		scan_code_name = scan_doc.name
		action_key = scan_doc.action_key
		source_doctype = scan_doc.source_doctype
		source_name = scan_doc.source_name

		action = _resolve_action(action_key)
		_validate_source_doctype(action["source_doctype"], source_doctype)
		_check_permission(action["allowed_roles"])

		if _can_open_existing_result(scan_doc, action_key):
			existing_result = _get_existing_success_result(
				action_key,
				source_doctype,
				source_name,
				scan_doc.name,
			)
			if existing_result:
				record_successful_scan(scan_doc.name, action_key)
				_log_scan(
					action=action_key,
					source_doctype=source_doctype,
					source_name=source_name,
					result="Success",
					device_info=device_info,
					scan_code=scan_doc.name,
					result_doctype=existing_result["doctype"],
					result_name=existing_result["name"],
				)
				frappe.local.flags.commit = True
				return {
					"success": True,
					"action": action_key,
					**existing_result,
				}

		validate_scan_code_row(scan_doc, action_key)

		payload = _payload_from_scan_code_registry(scan_doc, device_info)

		handler_result = _validate_handler_result(
			_call_handler(action["handler"], source_doctype, source_name, payload)
		)

		record_successful_scan(scan_doc.name, action_key)

		if handler_result.get("doctype") != "Scan Log":
			_log_scan(
				action=action_key,
				source_doctype=source_doctype,
				source_name=source_name,
				result="Success",
				device_info=device_info,
				scan_code=scan_doc.name,
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
			scan_code=scan_code_name,
			error_message=str(exc),
		)
		frappe.db.commit()
		raise
