"""Create Purchase Receipt drafts from Gate Pass (aligned with Desk create_from_gate_pass).

Desk Server Script and ASN scan receipt creation share these mappers and overlays.
"""

from __future__ import annotations

from typing import Any

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.utils import cint, flt


def _set_field(doc: Any, fieldname: str, value) -> None:
	if value is None:
		return
	meta = getattr(doc, "meta", None)
	if meta is not None and hasattr(meta, "has_field") and not meta.has_field(fieldname):
		return
	setattr(doc, fieldname, value)


def ensure_load_after_mapping(doc: Any) -> None:
	set_onload = getattr(doc, "set_onload", None)
	if callable(set_onload):
		set_onload("load_after_mapping", True)
		return
	onload = getattr(doc, "_onload", None)
	if onload is None:
		doc._onload = {"load_after_mapping": True}
	elif isinstance(onload, dict):
		onload["load_after_mapping"] = True


def _child_rows(doc: Any, fieldname: str) -> list:
	if isinstance(doc, dict):
		return list(doc.get(fieldname) or [])
	get = getattr(doc, "get", None)
	if callable(get):
		return list(get(fieldname) or [])
	return list(getattr(doc, fieldname, None) or [])


def _row_value(row: Any, fieldname: str):
	if isinstance(row, dict):
		return row.get(fieldname)
	return getattr(row, fieldname, None)


def gate_pass_receive_qty(row: Any) -> float:
	receive_qty = flt(_row_value(row, "receive_qty"))
	return receive_qty if receive_qty > 0 else flt(_row_value(row, "recieve_qty"))


def collect_receive_rows_by_po_item(gate_pass: Any) -> dict[str, list[tuple[Any, float]]]:
	"""Gate Pass rows with Receive Qty, in row order, grouped by Purchase Order Item.

	An ASN may ship one order line as several lines (one per batch), so one order line
	can have several Gate Pass rows; each keeps its own qty.
	"""
	rows_by_poi: dict[str, list[tuple[Any, float]]] = {}
	for row in _child_rows(gate_pass, "items"):
		poi = _row_value(row, "purchase_order_item")
		if not poi:
			continue
		receive_qty = gate_pass_receive_qty(row)
		if receive_qty <= 0:
			continue
		rows_by_poi.setdefault(poi, []).append((row, receive_qty))
	return rows_by_poi


def apply_item_branches(target: Any, gate_pass: Any) -> None:
	branch = getattr(gate_pass, "branch", None)
	if not branch:
		return
	for item in _child_rows(target, "items"):
		_set_field(item, "branch", branch)


def overlay_gate_pass_onto_mapped_pr(purchase_receipt: Any, gate_pass: Any) -> Any:
	if getattr(gate_pass, "company", None):
		_set_field(purchase_receipt, "company", gate_pass.company)
	if getattr(gate_pass, "branch", None):
		_set_field(purchase_receipt, "branch", gate_pass.branch)
	if getattr(gate_pass, "supplier", None):
		_set_field(purchase_receipt, "supplier", gate_pass.supplier)

	_set_field(purchase_receipt, "vehicle_no", getattr(gate_pass, "vehicle_number", None))
	_set_field(purchase_receipt, "driver_name", getattr(gate_pass, "driver_name", None))
	_set_field(purchase_receipt, "custom_invoice_no", getattr(gate_pass, "invoice_number", None))
	_set_field(purchase_receipt, "custom_invoice_date", getattr(gate_pass, "invoice_date", None))
	_set_field(purchase_receipt, "custom_delivery_challan_no", getattr(gate_pass, "challan_number", None))
	_set_field(purchase_receipt, "custom_delivery_challan_date", getattr(gate_pass, "challan_date", None))
	_set_field(purchase_receipt, "custom_purchase_receipt_type", getattr(gate_pass, "gate_pass_type", None))
	_set_field(purchase_receipt, "custom_gate_pass_reference", gate_pass.name)
	apply_item_branches(purchase_receipt, gate_pass)

	rows_by_poi = collect_receive_rows_by_po_item(gate_pass)
	for item in _child_rows(purchase_receipt, "items"):
		gp_rows = rows_by_poi.get(item.purchase_order_item)
		if not gp_rows:
			continue
		# One receipt row per Gate Pass row: the mapper gives one row per order line.
		template = (
			item.as_dict(no_default_fields=True, no_child_table_fields=True) if len(gp_rows) > 1 else None
		)
		for pos, (gp_row, qty) in enumerate(gp_rows):
			target = item if pos == 0 else purchase_receipt.append("items", dict(template))
			conversion = flt(target.conversion_factor) or 1.0
			target.qty = qty
			target.received_qty = qty
			target.stock_qty = qty * conversion
			_set_field(target, "custom_gate_pass", gate_pass.name)
			_set_field(target, "custom_gate_pass_item", _row_value(gp_row, "name"))

	ensure_load_after_mapping(purchase_receipt)
	return purchase_receipt


def validate_gate_pass_for_purchase_receipt(gate_pass: Any) -> None:
	if cint(gate_pass.docstatus) != 1:
		frappe.throw(_("Submit the Gate Pass before creating a Purchase Receipt"))
	if gate_pass.entry_type != "Gate In":
		frappe.throw(_("Purchase Receipt Create requires Gate In"))
	if gate_pass.document_reference != "Purchase Order" or not gate_pass.reference_number:
		frappe.throw(_("Purchase Receipt Create requires a Purchase Order Document Reference"))


def throw_if_open_purchase_receipt_for_gate_pass(gate_pass_name: str) -> None:
	if not frappe.get_meta("Purchase Receipt").has_field("custom_gate_pass_reference"):
		return
	existing = frappe.get_all(
		"Purchase Receipt",
		filters={"custom_gate_pass_reference": gate_pass_name, "docstatus": ["!=", 2]},
		fields=["name"],
		limit=1,
	)
	if existing:
		frappe.throw(_("Purchase Receipt {0} already exists for this Gate Pass").format(existing[0]["name"]))


def map_purchase_receipt_draft_from_gate_pass(gate_pass: Any, *, recalculate_taxes: bool = False):
	"""PO-mapped Purchase Receipt draft with Gate Pass qty and site overlays applied."""
	validate_gate_pass_for_purchase_receipt(gate_pass)
	rows_by_poi = collect_receive_rows_by_po_item(gate_pass)
	if not rows_by_poi:
		frappe.throw(_("No Gate Pass lines with Receive Qty to create a Purchase Receipt"))

	doc = make_purchase_receipt(
		gate_pass.reference_number,
		args={"filtered_children": list(rows_by_poi)},
	)
	overlay_gate_pass_onto_mapped_pr(doc, gate_pass)
	if recalculate_taxes:
		doc.run_method("calculate_taxes_and_totals")
	return doc


@frappe.whitelist(methods=["GET"])
def create_from_gate_pass(source_name: str) -> None:
	"""Desk-aligned Create from Gate Pass. Returns an unsaved Purchase Receipt draft."""
	frappe.only_for(("Stock User", "Stock Manager"))
	if not source_name:
		frappe.throw(_("Gate Pass name is required"))

	gate_pass = frappe.get_doc("Gate Pass", source_name)
	frappe.has_permission("Gate Pass", "read", gate_pass, throw=True)
	frappe.has_permission("Purchase Receipt", "create", throw=True)
	if gate_pass.entry_type != "Gate In" or gate_pass.document_reference != "Purchase Order":
		frappe.throw(
			_("No Create mapping for {0} + {1}").format(gate_pass.entry_type, gate_pass.document_reference)
		)

	throw_if_open_purchase_receipt_for_gate_pass(gate_pass.name)
	doc = map_purchase_receipt_draft_from_gate_pass(gate_pass, recalculate_taxes=True)
	frappe.response["message"] = doc
