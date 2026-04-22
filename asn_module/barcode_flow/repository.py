from __future__ import annotations

from typing import Any

import frappe


def get_transitions_for_source_node_action(*, flow: str, source_node: str, action: str) -> list[Any]:
	flow = (flow or "").strip()
	source_node = (source_node or "").strip()
	action = (action or "").strip()
	if not flow or not source_node or not action:
		return []

	names = frappe.get_all(
		"Barcode Flow Transition",
		filters={"flow": flow, "source_node": source_node, "action": action},
		pluck="name",
		order_by="priority asc, creation asc, name asc",
	)
	rows = [frappe.get_doc("Barcode Flow Transition", name) for name in names]
	return [row for row in rows if _is_enabled(row)]


def get_condition(condition_name: str) -> Any | None:
	name = (condition_name or "").strip()
	if not name:
		return None

	try:
		condition = frappe.get_doc("Barcode Flow Condition", name)
	except getattr(frappe, "DoesNotExistError", Exception):
		return None

	if not _is_enabled(condition):
		return None
	return condition


def _is_enabled(row: Any) -> bool:
	for fieldname in ("enabled", "is_enabled", "is_active"):
		value = _get_value(row, fieldname, None)
		if value is None:
			continue
		return bool(int(value or 0))
	return True


def _get_value(row: Any, fieldname: str, default: Any = "") -> Any:
	if isinstance(row, dict):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)
