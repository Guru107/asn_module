from __future__ import annotations

import json
from typing import Any

import frappe

from asn_module.barcode_process_flow import capabilities

DEFAULT_STANDARD_FLOW_NAME = "System::Default::StandardHandlers"
DEFAULT_STANDARD_FLOW_DESCRIPTION = (
	"System-generated baseline flow with all built-in standard handlers."
)
DEFAULT_STANDARD_MAPPING_SET_NAME = "System::Default::NoopMapping"
DEFAULT_STANDARD_MAPPING_SET_DESCRIPTION = (
	"System-generated placeholder mapping set used by standard-handler flow steps."
)


@frappe.whitelist()
def get_standard_handler_templates(from_doctype: str | None = None) -> list[dict[str, Any]]:
	"""Return runtime-supported built-in handler templates for the current ERP version."""
	return capabilities.get_supported_templates(from_doctype=from_doctype)


def get_canonical_actions() -> list[dict[str, Any]]:
	"""Compatibility helper retained for bench commands/tests.

	In the hard-cut model there is no QR Action Registry; this returns capability-backed
	handler descriptors for observability tooling.
	"""
	rows = []
	for template in get_standard_handler_templates():
		rows.append(
			{
				"action_key": template["key"],
				"handler_method": template["handler"],
				"source_doctype": template["from_doctype"],
				"roles": [],
			}
		)
	return rows


def sync_qr_action_definitions():
	"""Legacy no-op retained to keep existing install hooks import-safe."""
	return None


def register_actions():
	"""Legacy no-op retained to keep existing install hooks import-safe."""
	return None


def ensure_default_standard_handler_flow() -> str | None:
	"""Create/reconcile one system-generated default Barcode Process Flow."""
	templates = get_standard_handler_templates()
	if not templates:
		return None

	mapping_set_name = _ensure_default_standard_mapping_set()
	steps = [_template_to_default_step(template, mapping_set_name) for template in templates]

	flow_name = DEFAULT_STANDARD_FLOW_NAME
	if frappe.db.exists("Barcode Process Flow", flow_name):
		flow_doc = frappe.get_doc("Barcode Process Flow", flow_name)
		flow_doc.is_active = 1
		flow_doc.company = ""
		flow_doc.description = DEFAULT_STANDARD_FLOW_DESCRIPTION
		flow_doc.set("steps", steps)
		flow_doc.save(ignore_permissions=True)
		return flow_name

	flow_doc = frappe.get_doc(
		{
			"doctype": "Barcode Process Flow",
			"flow_name": flow_name,
			"is_active": 1,
			"company": "",
			"description": DEFAULT_STANDARD_FLOW_DESCRIPTION,
			"steps": steps,
		}
	)
	flow_doc.insert(ignore_permissions=True)
	return (flow_doc.name or flow_name).strip() or flow_name


def _ensure_default_standard_mapping_set() -> str:
	name = DEFAULT_STANDARD_MAPPING_SET_NAME
	if frappe.db.exists("Barcode Mapping Set", name):
		return name

	mapping_set = frappe.get_doc(
		{
			"doctype": "Barcode Mapping Set",
			"mapping_set_name": name,
			"is_active": 1,
			"description": DEFAULT_STANDARD_MAPPING_SET_DESCRIPTION,
		}
	)
	mapping_set.insert(ignore_permissions=True)
	return name


def _template_to_default_step(template: dict[str, Any], mapping_set_name: str) -> dict[str, Any]:
	from_doctype = (template.get("from_doctype") or "").strip()
	to_doctype = (template.get("to_doctype") or "").strip()
	scan_action_key = (template.get("key") or "").strip()
	condition = _ensure_default_rule_for_template(template)
	return {
		"label": f"{from_doctype} -> {to_doctype}",
		"from_doctype": from_doctype,
		"to_doctype": to_doctype,
		"scan_action_key": scan_action_key,
		"execution_mode": "Mapping",
		"mapping_set": mapping_set_name,
		"condition": condition,
		"priority": 100,
		"generate_next_barcode": 1,
		"generation_mode": "hybrid",
		"is_active": 1,
	}


def _ensure_default_rule_for_template(template: dict[str, Any]) -> str:
	template_key = (template.get("key") or "").strip()
	doc_conditions = template.get("doc_conditions") or {}
	if not template_key or not isinstance(doc_conditions, dict) or not doc_conditions:
		return ""

	fieldname, values = next(iter(doc_conditions.items()))
	fieldname = str(fieldname or "").strip()
	normalized_values = [str(value or "").strip() for value in list(values or []) if str(value or "").strip()]
	if not fieldname or not normalized_values:
		return ""

	rule_name = f"System::Default::Rule::{template_key}"
	operator = "=" if len(normalized_values) == 1 else "in"
	value = normalized_values[0] if len(normalized_values) == 1 else json.dumps(normalized_values)
	description = f"Auto-generated condition for standard handler {template_key}"

	if frappe.db.exists("Barcode Rule", rule_name):
		rule_doc = frappe.get_doc("Barcode Rule", rule_name)
		rule_doc.is_active = 1
		rule_doc.scope = "header"
		rule_doc.field_path = fieldname
		rule_doc.operator = operator
		rule_doc.value = value
		rule_doc.description = description
		rule_doc.save(ignore_permissions=True)
		return rule_doc.name

	rule_doc = frappe.get_doc(
		{
			"doctype": "Barcode Rule",
			"rule_name": rule_name,
			"is_active": 1,
			"scope": "header",
			"field_path": fieldname,
			"operator": operator,
			"value": value,
			"description": description,
		}
	).insert(ignore_permissions=True)
	return rule_doc.name
