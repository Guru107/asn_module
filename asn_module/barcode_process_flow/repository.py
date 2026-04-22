from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe.utils import cint


@dataclass(frozen=True)
class StepRecord:
	flow_name: str
	flow_label: str
	step_name: str
	label: str
	from_doctype: str
	to_doctype: str
	execution_mode: str
	mapping_set: str | None
	server_script: str | None
	condition: str | None
	priority: int
	generate_next_barcode: bool
	generation_mode: str
	scan_action_key: str


def get_rule(rule_name: str | None):
	name = (rule_name or "").strip()
	if not name:
		return None
	if not frappe.db.exists("Barcode Rule", name):
		return None
	rule = frappe.get_doc("Barcode Rule", name)
	if cint(getattr(rule, "is_active", 1)) != 1:
		return None
	return rule


def get_mapping_set(mapping_set: str | None):
	name = (mapping_set or "").strip()
	if not name:
		return None
	if not frappe.db.exists("Barcode Mapping Set", name):
		return None
	doc = frappe.get_doc("Barcode Mapping Set", name)
	if cint(getattr(doc, "is_active", 1)) != 1:
		return None
	return doc


def get_active_steps_for_source(source_doc: Any, *, action_key: str | None = None) -> list[StepRecord]:
	source_doctype = (getattr(source_doc, "doctype", "") or "").strip()
	if not source_doctype:
		return []

	context = _build_context(source_doc)
	flow_names = frappe.get_all("Barcode Process Flow", filters={"is_active": 1}, pluck="name")
	rows: list[StepRecord] = []
	for flow_name in flow_names:
		flow = frappe.get_doc("Barcode Process Flow", flow_name)
		if not _flow_matches_context(flow, context):
			continue
		for step in flow.steps or []:
			if cint(getattr(step, "is_active", 1)) != 1:
				continue
			if (getattr(step, "from_doctype", "") or "").strip() != source_doctype:
				continue

			step_key = _step_scan_key(step)
			if action_key and action_key not in {step_key, (getattr(step, "name", "") or "").strip()}:
				continue

			rows.append(
				StepRecord(
					flow_name=flow.name,
					flow_label=(flow.flow_name or flow.name),
					step_name=(step.name or "").strip(),
					label=((step.label or "").strip() or f"{step.from_doctype} -> {step.to_doctype}"),
					from_doctype=(step.from_doctype or "").strip(),
					to_doctype=(step.to_doctype or "").strip(),
					execution_mode=(
						(getattr(step, "execution_mode", "Mapping") or "Mapping").strip() or "Mapping"
					),
					mapping_set=(getattr(step, "mapping_set", "") or "").strip() or None,
					server_script=(getattr(step, "server_script", "") or "").strip() or None,
					condition=(getattr(step, "condition", "") or "").strip() or None,
					priority=cint(getattr(step, "priority", 0) or 0),
					generate_next_barcode=bool(cint(getattr(step, "generate_next_barcode", 0) or 0)),
					generation_mode=(
						(getattr(step, "generation_mode", "hybrid") or "hybrid").strip().lower()
						or "hybrid"
					),
					scan_action_key=step_key,
				)
			)

	rows.sort(key=lambda row: (-row.priority, row.flow_name, row.label, row.step_name))
	return rows


def get_step_by_name(step_name: str | None):
	name = (step_name or "").strip()
	if not name:
		return None
	if not frappe.db.exists("Flow Step", name):
		return None
	return frappe.get_doc("Flow Step", name)


def _step_scan_key(step: Any) -> str:
	key = (getattr(step, "scan_action_key", "") or "").strip()
	if key:
		return key
	return (getattr(step, "name", "") or "").strip()


def _build_context(doc: Any) -> dict[str, str | None]:
	company = (getattr(doc, "company", "") or "").strip() or None
	warehouse = (
		(getattr(doc, "warehouse", "") or "").strip()
		or (getattr(doc, "set_warehouse", "") or "").strip()
		or None
	)
	supplier_type = (getattr(doc, "supplier_type", "") or "").strip() or None
	if not supplier_type:
		supplier = (getattr(doc, "supplier", "") or "").strip()
		if supplier:
			supplier_type = (
				(frappe.db.get_value("Supplier", supplier, "supplier_type") or "").strip() or None
			)
	return {
		"company": company,
		"warehouse": warehouse,
		"supplier_type": supplier_type,
	}


def _flow_matches_context(flow: Any, context: dict[str, str | None]) -> bool:
	for fieldname in ("company", "warehouse", "supplier_type"):
		flow_value = (getattr(flow, fieldname, "") or "").strip()
		if not flow_value:
			continue
		if flow_value != (context.get(fieldname) or ""):
			return False
	return True
