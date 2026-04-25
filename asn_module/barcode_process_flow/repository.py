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
	normalized_action_key = (action_key or "").strip()

	context = _build_context(source_doc)
	flows = frappe.get_all(
		"Barcode Process Flow",
		filters={"is_active": 1},
		fields=["name", "flow_name", "company"],
	)
	if not flows:
		return []

	active_flows = [flow for flow in flows if _flow_matches_context(flow, context)]
	if not active_flows:
		return []

	flow_by_name = {
		(_field_value(flow, "name") or "").strip(): flow
		for flow in active_flows
		if (_field_value(flow, "name") or "").strip()
	}
	if not flow_by_name:
		return []

	step_rows = frappe.get_all(
		"Flow Step",
		filters={
			"parenttype": "Barcode Process Flow",
			"parent": ["in", sorted(flow_by_name)],
			"is_active": 1,
			"from_doctype": source_doctype,
		},
		fields=[
			"name",
			"parent",
			"label",
			"from_doctype",
			"to_doctype",
			"execution_mode",
			"mapping_set",
			"server_script",
			"condition",
			"priority",
			"generate_next_barcode",
			"generation_mode",
			"scan_action_key",
		],
		order_by="parent asc, idx asc",
	)

	rows: list[StepRecord] = []
	for step in step_rows:
		flow_name = (_field_value(step, "parent") or "").strip()
		flow = flow_by_name.get(flow_name)
		if not flow:
			continue

		step_key = _step_scan_key(step)
		step_name = (_field_value(step, "name") or "").strip()
		if normalized_action_key and normalized_action_key not in {step_key, step_name}:
			continue

		from_doctype = (_field_value(step, "from_doctype") or "").strip()
		to_doctype = (_field_value(step, "to_doctype") or "").strip()
		rows.append(
			StepRecord(
				flow_name=flow_name,
				flow_label=(
					(_field_value(flow, "flow_name") or _field_value(flow, "name") or "").strip()
				),
				step_name=step_name,
				label=((_field_value(step, "label") or "").strip() or f"{from_doctype} -> {to_doctype}"),
				from_doctype=from_doctype,
				to_doctype=to_doctype,
				execution_mode=(
					(_field_value(step, "execution_mode") or "Mapping").strip() or "Mapping"
				),
				mapping_set=(_field_value(step, "mapping_set") or "").strip() or None,
				server_script=(_field_value(step, "server_script") or "").strip() or None,
				condition=(_field_value(step, "condition") or "").strip() or None,
				priority=cint(_field_value(step, "priority") or 0),
				generate_next_barcode=bool(cint(_field_value(step, "generate_next_barcode") or 0)),
				generation_mode=(
					(_field_value(step, "generation_mode") or "hybrid").strip().lower() or "hybrid"
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
	step = frappe.get_doc("Flow Step", name)
	if cint(getattr(step, "is_active", 1)) != 1:
		return None
	flow_name = (getattr(step, "parent", "") or getattr(step, "flow", "") or "").strip()
	if not flow_name:
		return None
	if not cint(frappe.db.get_value("Barcode Process Flow", flow_name, "is_active") or 0):
		return None
	return step


def has_conditioned_step_for_source_doctype(source_doctype: str | None) -> bool:
	doctype = (source_doctype or "").strip()
	if not doctype:
		return False

	active_flow_names = frappe.get_all("Barcode Process Flow", filters={"is_active": 1}, pluck="name")
	if not active_flow_names:
		return False

	rows = frappe.get_all(
		"Flow Step",
		filters={
			"parenttype": "Barcode Process Flow",
			"parent": ["in", active_flow_names],
			"is_active": 1,
			"from_doctype": doctype,
			"condition": ["!=", ""],
		},
		fields=["name"],
		limit_page_length=1,
	)
	return bool(rows)


def _step_scan_key(step: Any) -> str:
	key = (_field_value(step, "scan_action_key") or "").strip()
	if key:
		return key
	return (_field_value(step, "name") or "").strip()


def _build_context(doc: Any) -> dict[str, str | None]:
	company = _resolve_company(doc)
	return {
		"company": company,
	}


def _resolve_company(doc: Any) -> str | None:
	company = (getattr(doc, "company", "") or "").strip()
	if company:
		return company

	doctype = (getattr(doc, "doctype", "") or "").strip()
	docname = (getattr(doc, "name", "") or "").strip()
	if doctype != "ASN" or not docname:
		return None

	purchase_order = _first_linked_purchase_order(doc, docname)
	if not purchase_order:
		return None

	po_company = frappe.db.get_value("Purchase Order", purchase_order, "company")
	return (po_company or "").strip() or None


def _first_linked_purchase_order(doc: Any, docname: str) -> str | None:
	for row in list(getattr(doc, "items", []) or []):
		po = (getattr(row, "purchase_order", "") or "").strip()
		if po:
			return po

	rows = frappe.get_all(
		"ASN Item",
		filters={"parenttype": "ASN", "parent": docname, "purchase_order": ["!=", ""]},
		fields=["purchase_order"],
		order_by="idx asc",
		limit=1,
	)
	if not rows:
		return None
	return (rows[0].get("purchase_order") or "").strip() or None


def _flow_matches_context(flow: Any, context: dict[str, str | None]) -> bool:
	for fieldname in ("company",):
		flow_value = (_field_value(flow, fieldname) or "").strip()
		if not flow_value:
			continue
		if flow_value != (context.get(fieldname) or ""):
			return False
	return True


def _field_value(source: Any, fieldname: str) -> Any:
	if isinstance(source, dict):
		return source.get(fieldname)
	return getattr(source, fieldname, None)
