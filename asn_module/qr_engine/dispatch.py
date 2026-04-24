import frappe
from frappe import _

from asn_module.barcode_process_flow.runtime import dispatch_from_scan
from asn_module.qr_engine.scan_codes import (
	get_scan_code_doc,
	normalize_scan_code,
	record_successful_scan,
	validate_scan_code_row,
)


class PermissionDeniedError(frappe.PermissionError):
	pass


class ScanCodeNotFoundError(frappe.ValidationError):
	pass


def _get_failure_log_identity(source_doctype: str | None, source_name: str | None) -> tuple[str, str]:
	try:
		if source_doctype and source_name and frappe.db.exists("DocType", source_doctype):
			if frappe.db.exists(source_doctype, source_name):
				return source_doctype, source_name
	except Exception:
		pass

	return "DocType", "Scan Code"


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


@frappe.whitelist(allow_guest=False)
def dispatch(code: str | None = None, device_info: str = "Desktop") -> dict:
	"""Resolve a short scan ``code`` (URL param or raw) and execute configured flow step(s)."""
	if not code:
		code = frappe.form_dict.get("code")

	raw_input = (code or "").strip()
	normalized = normalize_scan_code(raw_input)

	action_key = "unknown"
	source_doctype = "DocType"
	source_name = "Scan Code"
	flow_name = None
	step_name = None
	step_label = None

	try:
		if not normalized:
			if raw_input:
				raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))
			raise ScanCodeNotFoundError(_("Missing scan code."))

		scan_doc = get_scan_code_doc(normalized)
		if not scan_doc:
			raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))

		action_key = (scan_doc.action_key or "").strip()
		source_doctype = scan_doc.source_doctype
		source_name = scan_doc.source_name

		validate_scan_code_row(scan_doc, action_key)
		source_doc = frappe.get_doc(source_doctype, source_name)

		result, matched_steps = dispatch_from_scan(scan_action_key=action_key, source_doc=source_doc)
		if matched_steps:
			first_step = matched_steps[0]
			flow_name = first_step.flow_label
			step_name = first_step.step_name
			step_label = first_step.label

		record_successful_scan(scan_doc.name, action_key)

		if result.get("doctype") != "Scan Log":
			_log_scan(
				action=action_key,
				source_doctype=source_doctype,
				source_name=source_name,
				result="Success",
				device_info=device_info,
				result_doctype=result.get("doctype"),
				result_name=result.get("name"),
				barcode_flow_definition=flow_name,
				barcode_flow_transition=step_label,
				scope_resolution_key=step_name,
			)
		frappe.local.flags.commit = True

		response = {
			"success": True,
			"action": action_key,
			"doctype": result["doctype"],
			"name": result["name"],
			"url": result["url"],
			"message": result.get("message", ""),
			"flow_name": flow_name,
			"step_name": step_name,
			"step_label": step_label,
		}
		if result.get("generated_scan_codes"):
			response["generated_scan_codes"] = result["generated_scan_codes"]
		if result.get("results"):
			response["results"] = result["results"]
		return response
	except Exception as exc:
		failure_source_doctype, failure_source_name = _get_failure_log_identity(source_doctype, source_name)
		_log_scan(
			action=action_key,
			source_doctype=failure_source_doctype,
			source_name=failure_source_name,
			result="Failure",
			device_info=device_info,
			error_message=str(exc),
			barcode_flow_definition=flow_name,
			barcode_flow_transition=step_label,
			scope_resolution_key=step_name,
		)
		frappe.db.commit()
		raise
