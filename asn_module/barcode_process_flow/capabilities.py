from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import Any

import frappe

_HANDLER_TEMPLATES: list[dict[str, Any]] = [
	{
		"key": "asn_to_purchase_receipt",
		"from_doctype": "ASN",
		"to_doctype": "Purchase Receipt",
		"handler": "asn_module.handlers.purchase_receipt.create_from_asn",
	},
	{
		"key": "purchase_receipt_to_purchase_invoice",
		"from_doctype": "Purchase Receipt",
		"to_doctype": "Purchase Invoice",
		"handler": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
	},
	{
		"key": "qi_accepted_to_stock_transfer",
		"from_doctype": "Quality Inspection",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.handlers.stock_transfer.create_from_quality_inspection",
	},
	{
		"key": "qi_rejected_to_purchase_return",
		"from_doctype": "Quality Inspection",
		"to_doctype": "Purchase Receipt",
		"handler": "asn_module.handlers.purchase_return.create_from_quality_inspection",
	},
	{
		"key": "sco_to_send_to_subcontractor",
		"from_doctype": "Subcontracting Order",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order",
	},
	{
		"key": "sco_to_subcontracting_receipt",
		"from_doctype": "Subcontracting Order",
		"to_doctype": "Subcontracting Receipt",
		"handler": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
	},
	{
		"key": "asn_to_subcontracting_receipt",
		"from_doctype": "ASN",
		"to_doctype": "Subcontracting Receipt",
		"handler": "asn_module.barcode_process_flow.handlers.create_subcontracting_receipt_from_asn",
	},
	{
		"key": "mr_purchase_to_po",
		"from_doctype": "Material Request",
		"to_doctype": "Purchase Order",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_purchase_order",
		"doc_conditions": {"material_request_type": ["Purchase"]},
	},
	{
		"key": "mr_subcontracting_to_po",
		"from_doctype": "Material Request",
		"to_doctype": "Purchase Order",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_purchase_order",
		"min_erp_major": 16,
		"doc_conditions": {"material_request_type": ["Subcontracting"]},
	},
	{
		"key": "mr_to_rfq",
		"from_doctype": "Material Request",
		"to_doctype": "Request for Quotation",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_rfq",
	},
	{
		"key": "mr_to_supplier_quotation",
		"from_doctype": "Material Request",
		"to_doctype": "Supplier Quotation",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_supplier_quotation",
	},
	{
		"key": "mr_transfer_to_stock_entry",
		"from_doctype": "Material Request",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_stock_entry",
		"doc_conditions": {"material_request_type": ["Material Transfer"]},
	},
	{
		"key": "mr_issue_to_stock_entry",
		"from_doctype": "Material Request",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_stock_entry",
		"doc_conditions": {"material_request_type": ["Material Issue"]},
	},
	{
		"key": "mr_customer_provided_to_stock_entry",
		"from_doctype": "Material Request",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_stock_entry",
		"doc_conditions": {"material_request_type": ["Customer Provided"]},
	},
	{
		"key": "mr_transfer_to_in_transit_stock_entry",
		"from_doctype": "Material Request",
		"to_doctype": "Stock Entry",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_in_transit_stock_entry",
		"doc_conditions": {"material_request_type": ["Material Transfer"]},
	},
	{
		"key": "mr_manufacture_to_work_order",
		"from_doctype": "Material Request",
		"to_doctype": "Work Order",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_work_order",
		"doc_conditions": {"material_request_type": ["Manufacture"]},
	},
	{
		"key": "mr_to_pick_list",
		"from_doctype": "Material Request",
		"to_doctype": "Pick List",
		"handler": "asn_module.barcode_process_flow.handlers.material_request_to_pick_list",
	},
]


@lru_cache(maxsize=1)
def get_erp_major() -> int:
	try:
		erpnext = import_module("erpnext")
		version = str(getattr(erpnext, "__version__", ""))
	except Exception:
		version = str(frappe.get_attr("frappe.__version__") or "")

	parts = version.split(".")
	try:
		return int(parts[0])
	except (TypeError, ValueError):
		return 0


def get_supported_templates(*, from_doctype: str | None = None) -> list[dict[str, Any]]:
	erp_major = get_erp_major()
	templates: list[dict[str, Any]] = []
	for row in _HANDLER_TEMPLATES:
		if from_doctype and row.get("from_doctype") != from_doctype:
			continue
		if not _is_version_supported(row, erp_major):
			continue
		templates.append(dict(row))
	return templates


def get_supported_pairs(from_doctype: str | None = None) -> list[tuple[str, str, str]]:
	return [
		(str(row["from_doctype"]), str(row["to_doctype"]), str(row["key"]))
		for row in get_supported_templates(from_doctype=from_doctype)
	]


def get_standard_handler(
	from_doctype: str,
	to_doctype: str,
	source_doc: Any | None = None,
) -> str | None:
	for row in get_supported_templates(from_doctype=from_doctype):
		if row.get("to_doctype") != to_doctype:
			continue
		if source_doc and not _doc_matches_conditions(source_doc, row.get("doc_conditions") or {}):
			continue
		return str(row.get("handler") or "") or None
	return None


def _is_version_supported(template: dict[str, Any], erp_major: int) -> bool:
	min_major = int(template.get("min_erp_major") or 0)
	max_major = int(template.get("max_erp_major") or 999)
	return min_major <= erp_major <= max_major


def _doc_matches_conditions(doc: Any, conditions: dict[str, list[str]]) -> bool:
	for fieldname, expected_values in conditions.items():
		actual = str(getattr(doc, fieldname, "") or "").strip()
		if actual not in expected_values:
			return False
	return True
