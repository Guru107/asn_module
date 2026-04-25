from __future__ import annotations

from dataclasses import asdict
from typing import Any

import frappe
from frappe import _

from asn_module.barcode_process_flow import capabilities, mapping, repository, rules

_GENERATE_NOW = {"immediate", "hybrid"}


class StepNotFoundError(frappe.ValidationError):
	pass


class AmbiguousStepError(frappe.ValidationError):
	pass


def dispatch_from_scan(*, scan_action_key: str, source_doc: Any) -> tuple[dict, list[repository.StepRecord]]:
	candidates = repository.get_active_steps_for_source(source_doc, action_key=scan_action_key)
	if not candidates:
		raise StepNotFoundError(
			_("No active Barcode Process Flow step matched scan action {0} for {1}").format(
				scan_action_key,
				getattr(source_doc, "doctype", "Document"),
			)
		)

	eligible = [step for step in candidates if _is_condition_satisfied(step, source_doc)]
	if not eligible:
		raise StepNotFoundError(
			_("No eligible Barcode Process Flow step matched scan action {0}").format(scan_action_key)
		)

	winners = _pick_winners(eligible)
	contracts = [execute_step(step=step, source_doc=source_doc) for step in winners]
	response = dict(contracts[0])
	if len(contracts) > 1:
		response["results"] = contracts
	response["matched_steps"] = [_serialize_step(step) for step in winners]
	return response, winners


def resolve_eligible_steps(
	steps: list[repository.StepRecord], source_doc: Any
) -> list[repository.StepRecord]:
	eligible = [step for step in steps if _is_condition_satisfied(step, source_doc)]
	if not eligible:
		return []
	return _pick_winners(eligible)


def generate_codes_for_source_doc(*, source_doc: Any, conditioned_only: bool = False) -> list[dict]:
	steps = repository.get_active_steps_for_source(source_doc)
	if conditioned_only:
		steps = [step for step in steps if (step.condition or "").strip()]
	winners = resolve_eligible_steps(steps, source_doc)
	if not winners:
		return []
	return _generate_codes_for_steps(source_doc=source_doc, steps=winners)


def execute_step(*, step: repository.StepRecord, source_doc: Any) -> dict:
	execution_mode = (step.execution_mode or "Mapping").strip()
	if execution_mode == "Server Script":
		contract = _execute_server_script(step=step, source_doc=source_doc)
	else:
		contract = _execute_mapping(step=step, source_doc=source_doc)

	result = dict(contract)
	result["flow_name"] = step.flow_name
	result["step_label"] = step.label
	result["step_name"] = step.step_name
	result["scan_action_key"] = step.scan_action_key
	result["generated_scan_codes"] = []

	if step.generate_next_barcode and contract.get("doctype") != "Scan Log":
		result["generated_scan_codes"] = _generate_followup_codes(result)

	return result


def _execute_mapping(*, step: repository.StepRecord, source_doc: Any) -> dict:
	handler_path = capabilities.get_standard_handler(
		from_doctype=step.from_doctype,
		to_doctype=step.to_doctype,
		source_doc=source_doc,
		action_key=step.scan_action_key,
	)
	if handler_path:
		handler = frappe.get_attr(handler_path)
		return _validate_contract(handler(step.from_doctype, source_doc.name, {}))

	mapping_set = repository.get_mapping_set(step.mapping_set)
	if not mapping_set:
		raise frappe.ValidationError(_("Mapping Set is required for step {0}").format(step.label))

	target_doc = mapping.build_target_doc(
		source_doc=source_doc,
		mapping_rows=list(mapping_set.rows or []),
		target_doctype=step.to_doctype,
	)
	target_doc.insert(ignore_permissions=True)
	return _doc_contract(target_doc)


def _execute_server_script(*, step: repository.StepRecord, source_doc: Any) -> dict:
	if not step.server_script:
		raise frappe.ValidationError(_("Server Script is required for step {0}").format(step.label))

	script = frappe.get_doc("Server Script", step.server_script)
	response = script.execute_method() or {}
	if not isinstance(response, dict):
		raise frappe.ValidationError(_("Server Script {0} must return a dict").format(step.server_script))

	contract = {
		"doctype": response.get("doctype"),
		"name": response.get("name"),
		"url": response.get("url"),
		"message": response.get("message") or "",
	}
	return _validate_contract(contract)


def _generate_followup_codes(result: dict[str, Any]) -> list[dict]:
	target_doctype = (result.get("doctype") or "").strip()
	target_name = (result.get("name") or "").strip()
	if not target_doctype or not target_name:
		return []

	target_doc = frappe.get_doc(target_doctype, target_name)
	next_steps = repository.get_active_steps_for_source(target_doc)
	winners = resolve_eligible_steps(next_steps, target_doc)
	if not winners:
		return []

	return _generate_codes_for_steps(source_doc=target_doc, steps=winners)


def _generate_codes_for_steps(*, source_doc: Any, steps: list[repository.StepRecord]) -> list[dict]:
	target_doctype = (getattr(source_doc, "doctype", "") or "").strip()
	target_name = (getattr(source_doc, "name", "") or "").strip()
	if not target_doctype or not target_name:
		return []

	generated: list[dict] = []
	for step in steps:
		if not step.generate_next_barcode:
			continue
		if step.generation_mode not in _GENERATE_NOW:
			continue
		from asn_module.qr_engine.generate import generate_barcode, generate_qr

		qr_result = generate_qr(step.scan_action_key, target_doctype, target_name)
		barcode_result = generate_barcode(step.scan_action_key, target_doctype, target_name)
		key_fragment = _safe_file_segment(step.step_name or step.scan_action_key)
		qr_file_url = _attach_followup_image(
			doctype=target_doctype,
			docname=target_name,
			filename=f"{target_name}-{key_fragment}-qr.png",
			image_base64=qr_result["image_base64"],
		)
		barcode_file_url = _attach_followup_image(
			doctype=target_doctype,
			docname=target_name,
			filename=f"{target_name}-{key_fragment}-barcode.png",
			image_base64=barcode_result["image_base64"],
		)
		generated.append(
			{
				"action_key": step.scan_action_key,
				"flow_step": step.step_name or None,
				"scan_code": qr_result.get("scan_code") or barcode_result.get("scan_code"),
				"human_readable": qr_result.get("human_readable")
				or barcode_result.get("human_readable")
				or "",
				"generation_mode": step.generation_mode,
				"qr_file_url": qr_file_url,
				"barcode_file_url": barcode_file_url,
			}
		)
	return generated


def _attach_followup_image(*, doctype: str, docname: str, filename: str, image_base64: str) -> str:
	from frappe.utils.file_manager import save_file

	file_doc = save_file(
		filename,
		image_base64,
		doctype,
		docname,
		is_private=0,
		decode=True,
	)
	return file_doc.file_url


def _safe_file_segment(value: str) -> str:
	segment = (value or "").strip().replace("/", "-").replace("\\", "-")
	return segment or "step"


def _pick_winners(steps: list[repository.StepRecord]) -> list[repository.StepRecord]:
	if not steps:
		return []
	top_priority = max(step.priority for step in steps)
	winners = [step for step in steps if step.priority == top_priority]
	winners.sort(key=lambda row: (row.flow_name, row.label, row.step_name))
	return winners


def _is_condition_satisfied(step: repository.StepRecord, source_doc: Any) -> bool:
	condition_name = (step.condition or "").strip()
	if not condition_name:
		return True

	rule = repository.get_rule(condition_name)
	if not rule:
		return False
	return rules.evaluate_rule(source_doc, rule)


def _doc_contract(doc: Any) -> dict:
	route = frappe.scrub(doc.doctype).replace("_", "-")
	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"url": f"/app/{route}/{doc.name}",
		"message": _("{0} {1} created").format(doc.doctype, doc.name),
	}


def _validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(contract, dict):
		raise frappe.ValidationError(_("Handler result must be a dict"))
	missing = [key for key in ("doctype", "name", "url") if not contract.get(key)]
	if missing:
		raise frappe.ValidationError(_("Handler result missing keys: {0}").format(", ".join(missing)))
	return contract


def _serialize_step(step: Any) -> dict[str, Any]:
	try:
		return asdict(step)
	except TypeError:
		return {
			"flow_name": getattr(step, "flow_name", None),
			"flow_label": getattr(step, "flow_label", None),
			"step_name": getattr(step, "step_name", None),
			"label": getattr(step, "label", None),
			"from_doctype": getattr(step, "from_doctype", None),
			"to_doctype": getattr(step, "to_doctype", None),
			"priority": getattr(step, "priority", None),
			"scan_action_key": getattr(step, "scan_action_key", None),
		}
