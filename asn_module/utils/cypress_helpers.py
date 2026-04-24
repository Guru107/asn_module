from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, nowdate


def _ensure_supplier_portal_user(
	*,
	supplier_name: str,
	portal_email: str,
	portal_password: str,
) -> tuple[frappe.model.document.Document, str, str]:
	supplier_docname = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
	if supplier_docname:
		supplier = frappe.get_doc("Supplier", supplier_docname)
	else:
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": supplier_name,
				"supplier_group": "All Supplier Groups",
				"supplier_type": "Individual",
			}
		).insert(ignore_permissions=True)

	if frappe.db.exists("User", portal_email):
		portal_user = frappe.get_doc("User", portal_email)
	else:
		portal_user = frappe.get_doc(
			{
				"doctype": "User",
				"email": portal_email,
				"first_name": "Supplier",
				"send_welcome_email": 0,
				"user_type": "Website User",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("User", portal_user.name, "enabled", 1)

	from frappe.utils.password import update_password

	update_password(portal_user.name, portal_password)

	if not frappe.db.exists(
		"User Permission",
		{"user": portal_user.name, "allow": "Supplier", "for_value": supplier.name},
	):
		frappe.permissions.add_user_permission("Supplier", supplier.name, portal_user.name)

	portal_user_doc = frappe.get_doc("User", portal_user.name)
	if not any((row.role or "").strip() == "Supplier" for row in portal_user_doc.roles):
		portal_user_doc.append("roles", {"doctype": "Has Role", "role": "Supplier"})
		portal_user_doc.save(ignore_permissions=True)

	if not frappe.db.exists(
		"Portal User",
		{"parent": supplier.name, "parenttype": "Supplier", "user": portal_user.name},
	):
		frappe.get_doc(
			{
				"doctype": "Portal User",
				"parent": supplier.name,
				"parenttype": "Supplier",
				"parentfield": "portal_users",
				"user": portal_user.name,
			}
		).insert(ignore_permissions=True)

	return supplier, portal_user.name, portal_password


@frappe.whitelist()
def seed_minimal_asn():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)

	po = create_purchase_order(qty=10)
	asn = make_test_asn(
		purchase_order=po,
		supplier_invoice_no="NIGHTLY-" + frappe.generate_hash(length=8),
		qty=10,
	)
	asn.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()

	return {"asn_name": asn.name, "asn_status": asn.status, "supplier": asn.supplier}


@frappe.whitelist()
def seed_scan_station_context():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)
	from asn_module.qr_engine.scan_codes import get_or_create_scan_code
	from asn_module.setup_actions import register_actions

	register_actions()

	po = create_purchase_order(qty=10)
	asn = make_test_asn(
		purchase_order=po,
		supplier_invoice_no="SCAN-" + frappe.generate_hash(length=8),
		qty=10,
	)
	asn.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()

	scan_code_name = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
	scan_code_value = frappe.db.get_value("Scan Code", scan_code_name, "scan_code")

	return {
		"asn_name": asn.name,
		"scan_code": scan_code_value,
		"scan_code_name": scan_code_name,
	}


@frappe.whitelist()
def seed_supplier_context():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	supplier_name = "Test Supplier E2E"
	portal_email = "supplier_e2e@test.com"
	portal_password = "supplier_e2e"

	supplier, portal_user_name, portal_password = _ensure_supplier_portal_user(
		supplier_name=supplier_name,
		portal_email=portal_email,
		portal_password=portal_password,
	)

	from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

	po1 = create_purchase_order(qty=10, supplier=supplier.name)
	po2 = create_purchase_order(qty=5, supplier=supplier.name)

	return {
		"supplier": supplier.name,
		"portal_user": portal_user_name,
		"portal_password": portal_password,
		"purchase_orders": [
			{"name": po1.name, "items": [i.as_dict() for i in po1.items]},
			{"name": po2.name, "items": [i.as_dict() for i in po2.items]},
		],
	}


@frappe.whitelist()
def seed_supplier_large_po_context():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	supplier_name = "Test Supplier E2E"
	portal_email = "supplier_e2e@test.com"
	portal_password = "supplier_e2e"

	supplier, portal_user_name, portal_password = _ensure_supplier_portal_user(
		supplier_name=supplier_name,
		portal_email=portal_email,
		portal_password=portal_password,
	)

	from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

	po = create_purchase_order(qty=1, supplier=supplier.name, item_count=100, rate=10)
	return {
		"supplier": supplier.name,
		"portal_user": portal_user_name,
		"portal_password": portal_password,
		"purchase_order": {"name": po.name, "items": [i.as_dict() for i in po.items]},
	}


@frappe.whitelist()
def seed_asn_with_items():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)

	po = create_purchase_order(qty=10)
	asn = make_test_asn(purchase_order=po, qty=10)
	asn.insert(ignore_permissions=True)

	po2 = create_purchase_order(qty=5)
	po2_item = po2.items[0]
	asn.append(
		"items",
		{
			"item_code": po2_item.item_code,
			"qty": 5,
			"rate": po2_item.rate,
			"uom": po2_item.uom,
			"stock_uom": po2_item.stock_uom,
		},
	)
	asn.save(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()

	return {
		"asn_name": asn.name,
		"item_count": len(asn.items),
		"items": [{"name": i.name, "item_code": i.item_code, "qty": i.qty} for i in asn.items],
	}


@frappe.whitelist()
def seed_quality_inspection_context():
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)
	from asn_module.handlers.tests.test_stock_transfer import TestCreateStockTransfer

	fixture = TestCreateStockTransfer()
	po = create_purchase_order(qty=10)
	asn = make_test_asn(purchase_order=po, qty=10)
	asn.insert(ignore_permissions=True)

	pr = fixture._make_purchase_receipt_with_qi(
		"Accepted", submit_quality_inspection=False, submit_purchase_receipt=False
	)
	pr_name = pr[0].name
	accepted_qi = fixture._make_quality_inspection(pr_name, asn.items[0].item_code, "Accepted")
	rejected_qi = fixture._make_quality_inspection(pr_name, asn.items[0].item_code, "Rejected")

	return {
		"asn_name": asn.name,
		"pr_name": pr_name,
		"qi_accepted": accepted_qi.name,
		"qi_rejected": rejected_qi.name,
	}


def _require_e2e_seed_context() -> None:
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")


@frappe.whitelist()
def seed_standard_handler_dispatch_matrix() -> dict[str, Any]:
	"""Create a full standard-handler scan matrix for Cypress nightly coverage."""
	_require_e2e_seed_context()

	from asn_module.barcode_process_flow import capabilities
	from asn_module.qr_engine.scan_codes import get_or_create_scan_code

	run_id = frappe.generate_hash(length=8)
	templates = capabilities.get_supported_templates()
	template_keys = [str(row.get("key") or "").strip() for row in templates if row.get("key")]

	source_docs = _prepare_standard_handler_source_docs(
		run_id=run_id,
		template_keys=set(template_keys),
	)
	missing_source_keys = sorted([key for key in template_keys if key not in source_docs])
	if missing_source_keys:
		frappe.throw(
			_("Missing E2E source docs for standard handler keys: {0}").format(", ".join(missing_source_keys))
		)

	flow = frappe.get_doc(
		{
			"doctype": "Barcode Process Flow",
			"flow_name": f"E2E::StandardHandlers::{run_id}",
			"is_active": 1,
			"description": "Cypress nightly standard-handler dispatch matrix",
			"steps": [],
		}
	)
	mapping_cache: dict[tuple[str, str], str] = {}

	for template in templates:
		template_key = str(template.get("key") or "").strip()
		if not template_key:
			continue
		source = source_docs[template_key]
		from_doctype = str(template.get("from_doctype") or source["doctype"]).strip()
		to_doctype = str(template.get("to_doctype") or source["expected_doctype"]).strip()
		mapping_set = _ensure_e2e_mapping_set(
			mapping_cache=mapping_cache,
			run_id=run_id,
			source_doctype=from_doctype,
			target_doctype=to_doctype,
		)
		flow.append(
			"steps",
			{
				"label": f"E2E {template_key}",
				"from_doctype": from_doctype,
				"to_doctype": to_doctype,
				"scan_action_key": template_key,
				"execution_mode": "Mapping",
				"mapping_set": mapping_set,
				"priority": 10000,
				"generate_next_barcode": 0,
				"generation_mode": "runtime",
				"is_active": 1,
			},
		)

	negative_rule = frappe.get_doc(
		{
			"doctype": "Barcode Rule",
			"rule_name": f"E2E::Rule::NoMatch::{run_id}",
			"is_active": 1,
			"scope": "header",
			"field_path": "material_request_type",
			"operator": "=",
			"value": "Purchase",
		}
	).insert(ignore_permissions=True)
	negative_action_key = f"e2e_negative_condition_{run_id}"
	negative_source = source_docs["mr_issue_to_stock_entry"]
	negative_mapping_set = _ensure_e2e_mapping_set(
		mapping_cache=mapping_cache,
		run_id=run_id,
		source_doctype="Material Request",
		target_doctype="Purchase Order",
	)
	flow.append(
		"steps",
		{
			"label": f"E2E negative condition {run_id}",
			"from_doctype": "Material Request",
			"to_doctype": "Purchase Order",
			"scan_action_key": negative_action_key,
			"execution_mode": "Mapping",
			"mapping_set": negative_mapping_set,
			"condition": negative_rule.name,
			"priority": 10000,
			"generate_next_barcode": 0,
			"generation_mode": "runtime",
			"is_active": 1,
		},
	)
	flow.insert(ignore_permissions=True)

	cases: list[dict[str, Any]] = []
	for template in templates:
		template_key = str(template.get("key") or "").strip()
		if not template_key:
			continue
		source = source_docs[template_key]
		scan_code_name = get_or_create_scan_code(template_key, source["doctype"], source["name"])
		scan_code = frappe.db.get_value("Scan Code", scan_code_name, "scan_code")
		cases.append(
			{
				"template_key": template_key,
				"scan_action_key": template_key,
				"scan_code_name": scan_code_name,
				"scan_code": scan_code,
				"from_doctype": source["doctype"],
				"source_name": source["name"],
				"expected_doctype": source["expected_doctype"],
			}
		)

	negative_scan_code_name = get_or_create_scan_code(
		negative_action_key, negative_source["doctype"], negative_source["name"]
	)
	negative_scan_code = frappe.db.get_value("Scan Code", negative_scan_code_name, "scan_code")

	supported_keys = [case["template_key"] for case in cases]
	return {
		"erp_major": capabilities.get_erp_major(),
		"flow_name": flow.name,
		"template_count": len(templates),
		"cases": cases,
		"supported_template_keys": supported_keys,
		"version_checks": {
			"mr_subcontracting_to_po_supported": "mr_subcontracting_to_po" in supported_keys,
		},
		"negative_cases": [
			{
				"scan_action_key": negative_action_key,
				"scan_code_name": negative_scan_code_name,
				"scan_code": negative_scan_code,
			}
		],
	}


@frappe.whitelist()
def dispatch_scan_for_test(code: str, device_info: str = "Cypress") -> dict[str, Any]:
	"""Dispatch wrapper for Cypress assertions (captures failure text without raising HTTP errors)."""
	_require_e2e_seed_context()

	from asn_module.qr_engine.dispatch import dispatch

	try:
		return {
			"ok": True,
			"result": dispatch(code=code, device_info=device_info),
		}
	except Exception as exc:
		return {
			"ok": False,
			"error": str(exc),
		}


def _prepare_standard_handler_source_docs(
	*,
	run_id: str,
	template_keys: set[str],
) -> dict[str, dict[str, str]]:
	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)
	from asn_module.handlers.purchase_receipt import create_from_asn as create_purchase_receipt_from_asn
	from asn_module.handlers.tests.test_subcontracting import TestSubcontractingHandlers

	base_po = create_purchase_order(qty=10)
	company = base_po.company
	item_code = base_po.items[0].item_code
	supplier = (base_po.supplier or "").strip()
	target_warehouse = (base_po.items[0].warehouse or "").strip() or _ensure_warehouse(
		f"_Test E2E Target Warehouse {run_id}", company
	)
	_ensure_purchase_order_item_warehouse(base_po, target_warehouse)
	cost_center = _get_company_cost_center(company)
	source_warehouse = _ensure_warehouse(f"_Test E2E Source Warehouse {run_id}", company)
	if frappe.db.has_column("Item", "valuation_rate"):
		frappe.db.set_value("Item", item_code, "valuation_rate", 10, update_modified=False)
	_ensure_item_default_warehouse(item_code=item_code, company=company, warehouse=target_warehouse)
	mr_item_code = _ensure_item(
		item_code=f"_Test E2E MR Item {run_id}",
		company=company,
		warehouse=target_warehouse,
	)
	_ensure_item_default_warehouse(
		item_code=mr_item_code,
		company=company,
		warehouse=target_warehouse,
	)
	if supplier:
		_ensure_item_default_supplier(item_code=mr_item_code, company=company, supplier=supplier)
	if frappe.db.has_column("Item", "valuation_rate"):
		frappe.db.set_value("Item", mr_item_code, "valuation_rate", 10, update_modified=False)

	if frappe.db.has_column("Company", "default_wip_warehouse"):
		if not frappe.db.get_value("Company", company, "default_wip_warehouse"):
			frappe.db.set_value("Company", company, "default_wip_warehouse", target_warehouse)

	asn_for_pr_doc = make_test_asn(
		purchase_order=base_po,
		supplier_invoice_no=f"E2E-PR-{run_id}",
		qty=10,
	)
	_ensure_asn_item_warehouse(asn_for_pr_doc, target_warehouse)
	asn_for_pr = _create_submitted_asn(
		asn_for_pr_doc,
		real_asn_attachment_context=real_asn_attachment_context,
	)
	asn_for_pi_doc = make_test_asn(
		purchase_order=_create_e2e_purchase_order(
			create_purchase_order=create_purchase_order,
			qty=8,
			target_warehouse=target_warehouse,
		),
		supplier_invoice_no=f"E2E-PI-{run_id}",
		qty=8,
	)
	_ensure_asn_item_warehouse(asn_for_pi_doc, target_warehouse)
	asn_for_pi = _create_submitted_asn(
		asn_for_pi_doc,
		real_asn_attachment_context=real_asn_attachment_context,
	)
	pr_result = create_purchase_receipt_from_asn("ASN", asn_for_pi.name, payload={})
	purchase_receipt = frappe.get_doc("Purchase Receipt", pr_result["name"])
	if purchase_receipt.docstatus != 1:
		purchase_receipt.submit()
	purchase_receipt.reload()
	if frappe.db.has_column("Item", "inspection_required_before_purchase"):
		frappe.db.set_value(
			"Item",
			purchase_receipt.items[0].item_code,
			"inspection_required_before_purchase",
			1,
			update_modified=False,
		)
	accepted_qi = _create_submitted_quality_inspection(
		reference_name=purchase_receipt.name,
		item_code=purchase_receipt.items[0].item_code,
		purchase_receipt_item=purchase_receipt.items[0].name,
		status="Accepted",
		run_id=run_id,
	)
	rejected_qi = _create_submitted_quality_inspection(
		reference_name=purchase_receipt.name,
		item_code=purchase_receipt.items[0].item_code,
		purchase_receipt_item=purchase_receipt.items[0].name,
		status="Rejected",
		run_id=run_id,
	)

	sco = TestSubcontractingHandlers()._make_integration_subcontracting_order(company=company)
	asn_for_subcontracting = make_test_asn(
		purchase_order=frappe.get_doc("Purchase Order", sco.purchase_order),
		supplier_invoice_no=f"E2E-SCR-{run_id}",
		qty=6,
	)
	_ensure_asn_item_warehouse(asn_for_subcontracting, target_warehouse)
	if asn_for_subcontracting.meta.has_field("subcontracting_order"):
		asn_for_subcontracting.subcontracting_order = sco.name
	asn_for_subcontracting = _create_submitted_asn(
		asn_for_subcontracting,
		real_asn_attachment_context=real_asn_attachment_context,
	)

	mr_purchase = _create_material_request(
		material_request_type="Purchase",
		company=company,
		item_code=mr_item_code,
		qty=4,
		warehouse=target_warehouse,
		from_warehouse=None,
		cost_center=cost_center,
	)
	subcontract_fg_item = _ensure_item(
		item_code=f"_Test E2E Subcontract FG {run_id}",
		company=company,
		warehouse=target_warehouse,
		is_sub_contracted_item=1,
	)
	subcontract_rm_item = _ensure_item(
		item_code=f"_Test E2E Subcontract RM {run_id}",
		company=company,
		warehouse=source_warehouse,
	)
	subcontract_service_item = _ensure_item(
		item_code=f"_Test E2E Subcontract Service {run_id}",
		company=company,
		warehouse=target_warehouse,
		is_stock_item=0,
	)
	subcontract_bom = _ensure_default_bom(
		fg_item=subcontract_fg_item,
		rm_item=subcontract_rm_item,
		company=company,
		source_warehouse=source_warehouse,
	)
	_ensure_subcontracting_bom(
		fg_item=subcontract_fg_item,
		service_item=subcontract_service_item,
		finished_good_bom=subcontract_bom,
	)
	if supplier:
		_ensure_item_default_supplier(
			item_code=subcontract_fg_item,
			company=company,
			supplier=supplier,
		)
	if frappe.db.has_column("Item", "valuation_rate"):
		frappe.db.set_value("Item", subcontract_fg_item, "valuation_rate", 10, update_modified=False)
		frappe.db.set_value("Item", subcontract_rm_item, "valuation_rate", 5, update_modified=False)
	mr_subcontracting = None
	if "mr_subcontracting_to_po" in template_keys:
		mr_subcontracting = _create_material_request(
			material_request_type="Subcontracting",
			company=company,
			item_code=subcontract_fg_item,
			qty=3,
			warehouse=target_warehouse,
			from_warehouse=None,
			cost_center=cost_center,
		)
	mr_transfer = _create_material_request(
		material_request_type="Material Transfer",
		company=company,
		item_code=mr_item_code,
		qty=3,
		warehouse=target_warehouse,
		from_warehouse=source_warehouse,
		cost_center=cost_center,
		set_warehouse=target_warehouse,
		set_from_warehouse=source_warehouse,
	)
	mr_issue = _create_material_request(
		material_request_type="Material Issue",
		company=company,
		item_code=mr_item_code,
		qty=3,
		warehouse=target_warehouse,
		from_warehouse=source_warehouse,
		cost_center=cost_center,
		set_warehouse=source_warehouse,
	)
	mr_customer_provided = _create_material_request(
		material_request_type="Customer Provided",
		company=company,
		item_code=mr_item_code,
		qty=3,
		warehouse=target_warehouse,
		from_warehouse=source_warehouse,
		cost_center=cost_center,
		customer=_ensure_customer(run_id=run_id),
		set_from_warehouse=source_warehouse,
	)

	fg_item = _ensure_item(
		item_code=f"_Test E2E FG Item {run_id}",
		company=company,
		warehouse=target_warehouse,
	)
	rm_item = _ensure_item(
		item_code=f"_Test E2E RM Item {run_id}",
		company=company,
		warehouse=source_warehouse,
	)
	bom_name = _ensure_default_bom(
		fg_item=fg_item,
		rm_item=rm_item,
		company=company,
		source_warehouse=source_warehouse,
	)
	mr_manufacture = _create_material_request(
		material_request_type="Manufacture",
		company=company,
		item_code=fg_item,
		qty=2,
		warehouse=target_warehouse,
		from_warehouse=source_warehouse,
		cost_center=cost_center,
		bom_no=bom_name,
	)

	_ensure_transit_warehouse(company=company, run_id=run_id)

	source_docs = {
		"asn_to_purchase_receipt": {
			"doctype": "ASN",
			"name": asn_for_pr.name,
			"expected_doctype": "Purchase Receipt",
		},
		"purchase_receipt_to_purchase_invoice": {
			"doctype": "Purchase Receipt",
			"name": purchase_receipt.name,
			"expected_doctype": "Purchase Invoice",
		},
		"qi_accepted_to_stock_transfer": {
			"doctype": "Quality Inspection",
			"name": accepted_qi.name,
			"expected_doctype": "Stock Entry",
		},
		"qi_rejected_to_purchase_return": {
			"doctype": "Quality Inspection",
			"name": rejected_qi.name,
			"expected_doctype": "Purchase Receipt",
		},
		"sco_to_send_to_subcontractor": {
			"doctype": "Subcontracting Order",
			"name": sco.name,
			"expected_doctype": "Stock Entry",
		},
		"sco_to_subcontracting_receipt": {
			"doctype": "Subcontracting Order",
			"name": sco.name,
			"expected_doctype": "Subcontracting Receipt",
		},
		"asn_to_subcontracting_receipt": {
			"doctype": "ASN",
			"name": asn_for_subcontracting.name,
			"expected_doctype": "Subcontracting Receipt",
		},
		"mr_purchase_to_po": {
			"doctype": "Material Request",
			"name": mr_purchase.name,
			"expected_doctype": "Purchase Order",
		},
		"mr_to_rfq": {
			"doctype": "Material Request",
			"name": mr_purchase.name,
			"expected_doctype": "Request for Quotation",
		},
		"mr_to_supplier_quotation": {
			"doctype": "Material Request",
			"name": mr_purchase.name,
			"expected_doctype": "Supplier Quotation",
		},
		"mr_transfer_to_stock_entry": {
			"doctype": "Material Request",
			"name": mr_transfer.name,
			"expected_doctype": "Stock Entry",
		},
		"mr_issue_to_stock_entry": {
			"doctype": "Material Request",
			"name": mr_issue.name,
			"expected_doctype": "Stock Entry",
		},
		"mr_customer_provided_to_stock_entry": {
			"doctype": "Material Request",
			"name": mr_customer_provided.name,
			"expected_doctype": "Stock Entry",
		},
		"mr_transfer_to_in_transit_stock_entry": {
			"doctype": "Material Request",
			"name": mr_transfer.name,
			"expected_doctype": "Stock Entry",
		},
		"mr_manufacture_to_work_order": {
			"doctype": "Material Request",
			"name": mr_manufacture.name,
			"expected_doctype": "Work Order",
		},
		"mr_to_pick_list": {
			"doctype": "Material Request",
			"name": mr_transfer.name,
			"expected_doctype": "Pick List",
		},
	}
	if mr_subcontracting:
		source_docs["mr_subcontracting_to_po"] = {
			"doctype": "Material Request",
			"name": mr_subcontracting.name,
			"expected_doctype": "Purchase Order",
		}
	return source_docs


def _create_submitted_asn(asn_doc, *, real_asn_attachment_context):
	asn_doc.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn_doc.submit()
	asn_doc.reload()
	return asn_doc


def _ensure_asn_item_warehouse(asn_doc, warehouse: str) -> None:
	if not warehouse:
		return
	for row in list(getattr(asn_doc, "items", []) or []):
		if not hasattr(row, "warehouse"):
			continue
		if (str(getattr(row, "warehouse", "") or "")).strip():
			continue
		row.warehouse = warehouse


def _create_submitted_quality_inspection(
	*,
	reference_name: str,
	item_code: str,
	purchase_receipt_item: str,
	status: str,
	run_id: str,
):
	qi = frappe.get_doc(
		{
			"doctype": "Quality Inspection",
			"inspection_type": "Incoming",
			"reference_type": "Purchase Receipt",
			"reference_name": reference_name,
			"item_code": item_code,
			"sample_size": 1,
			"status": status,
			"manual_inspection": 1,
			"inspected_by": frappe.session.user,
			"purchase_receipt_item": purchase_receipt_item,
			"remarks": f"E2E {run_id} {status}",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Quality Inspection", qi.name, "status", status, update_modified=False)
	frappe.db.set_value("Quality Inspection", qi.name, "docstatus", 1, update_modified=False)
	qi.reload()
	return qi


def _create_e2e_purchase_order(*, create_purchase_order, qty: float, target_warehouse: str):
	po = create_purchase_order(qty=qty)
	_ensure_purchase_order_item_warehouse(po, target_warehouse)
	return po


def _ensure_purchase_order_item_warehouse(po: Any, warehouse: str) -> None:
	if not warehouse:
		return
	for row in list(getattr(po, "items", []) or []):
		if (str(getattr(row, "warehouse", "") or "")).strip():
			continue
		frappe.db.set_value(
			"Purchase Order Item",
			row.name,
			"warehouse",
			warehouse,
			update_modified=False,
		)
	po.reload()


def _ensure_e2e_mapping_set(
	*,
	mapping_cache: dict[tuple[str, str], str],
	run_id: str,
	source_doctype: str,
	target_doctype: str,
) -> str:
	cache_key = (source_doctype, target_doctype)
	if cache_key in mapping_cache:
		return mapping_cache[cache_key]

	mapping_set = frappe.get_doc(
		{
			"doctype": "Barcode Mapping Set",
			"mapping_set_name": f"E2E::MAP::{run_id}::{len(mapping_cache) + 1}",
			"is_active": 1,
			"source_doctype": source_doctype,
			"target_doctype": target_doctype,
			"rows": [],
		}
	).insert(ignore_permissions=True)
	mapping_cache[cache_key] = mapping_set.name
	return mapping_set.name


def _get_company_cost_center(company: str) -> str:
	cost_center = (frappe.db.get_value("Company", company, "cost_center") or "").strip()
	if cost_center:
		return cost_center
	return (
		frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
		or frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
		or ""
	)


def _ensure_warehouse(warehouse_name: str, company: str) -> str:
	existing_name = frappe.db.get_value(
		"Warehouse",
		{"warehouse_name": warehouse_name, "company": company},
		"name",
	)
	if existing_name:
		return existing_name
	return (
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": company,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_customer(*, run_id: str) -> str:
	customer_name = f"_Test E2E Customer {run_id}"
	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if existing:
		return existing
	customer_group = frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups"
	territory = frappe.db.get_value("Territory", {}, "name") or "All Territories"
	return (
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer_name,
				"customer_group": customer_group,
				"territory": territory,
				"customer_type": "Company",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_item(
	*,
	item_code: str,
	company: str,
	warehouse: str,
	is_stock_item: int = 1,
	is_sub_contracted_item: int = 0,
) -> str:
	existing = frappe.db.exists("Item", item_code)
	if existing:
		return item_code

	uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
	item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
	return (
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": uom,
				"is_stock_item": is_stock_item,
				"is_sub_contracted_item": is_sub_contracted_item if is_stock_item else 0,
				"item_defaults": [
					{
						"company": company,
						"default_warehouse": warehouse,
					}
				],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_item_default_supplier(*, item_code: str, company: str, supplier: str) -> None:
	if not supplier:
		return

	row_name = frappe.db.get_value(
		"Item Default",
		{
			"parent": item_code,
			"parenttype": "Item",
			"company": company,
		},
		"name",
	)
	if not row_name:
		row_name = (
			frappe.get_doc(
				{
					"doctype": "Item Default",
					"parent": item_code,
					"parenttype": "Item",
					"parentfield": "item_defaults",
					"company": company,
					"default_supplier": supplier,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	else:
		frappe.db.set_value(
			"Item Default",
			row_name,
			"default_supplier",
			supplier,
			update_modified=False,
		)


def _ensure_item_default_warehouse(*, item_code: str, company: str, warehouse: str) -> None:
	if not warehouse:
		return
	row_name = frappe.db.get_value(
		"Item Default",
		{
			"parent": item_code,
			"parenttype": "Item",
			"company": company,
		},
		"name",
	)
	if not row_name:
		frappe.get_doc(
			{
				"doctype": "Item Default",
				"parent": item_code,
				"parenttype": "Item",
				"parentfield": "item_defaults",
				"company": company,
				"default_warehouse": warehouse,
			}
		).insert(ignore_permissions=True)
		return
	frappe.db.set_value(
		"Item Default",
		row_name,
		"default_warehouse",
		warehouse,
		update_modified=False,
	)


def _ensure_subcontracting_bom(
	*,
	fg_item: str,
	service_item: str,
	finished_good_bom: str,
) -> str:
	existing = frappe.db.get_value(
		"Subcontracting BOM",
		{"finished_good": fg_item, "is_active": 1},
		"name",
	)
	if existing:
		return existing

	fg_uom = frappe.db.get_value("Item", fg_item, "stock_uom") or "Nos"
	service_uom = frappe.db.get_value("Item", service_item, "stock_uom") or fg_uom
	return (
		frappe.get_doc(
			{
				"doctype": "Subcontracting BOM",
				"is_active": 1,
				"finished_good": fg_item,
				"finished_good_qty": 1,
				"finished_good_uom": fg_uom,
				"finished_good_bom": finished_good_bom,
				"service_item": service_item,
				"service_item_qty": 1,
				"service_item_uom": service_uom,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_default_bom(
	*,
	fg_item: str,
	rm_item: str,
	company: str,
	source_warehouse: str,
) -> str:
	existing_bom = frappe.db.get_value("BOM", {"item": fg_item, "is_default": 1, "is_active": 1}, "name")
	if existing_bom:
		return existing_bom

	uom = frappe.db.get_value("Item", fg_item, "stock_uom") or "Nos"
	valuation_rate = frappe.db.get_value("Item", rm_item, "valuation_rate") or 1
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": fg_item,
			"company": company,
			"is_default": 1,
			"quantity": 1,
			"uom": uom,
			"items": [
				{
					"item_code": rm_item,
					"qty": 1,
					"uom": uom,
					"stock_uom": uom,
					"rate": valuation_rate,
					"source_warehouse": source_warehouse,
				}
			],
		}
	).insert(ignore_permissions=True)
	if bom.docstatus != 1:
		bom.submit()
	frappe.db.set_value("Item", fg_item, "default_bom", bom.name, update_modified=False)
	return bom.name


def _create_material_request(
	*,
	material_request_type: str,
	company: str,
	item_code: str,
	qty: float,
	warehouse: str,
	from_warehouse: str | None,
	cost_center: str,
	customer: str = "",
	bom_no: str = "",
	set_warehouse: str = "",
	set_from_warehouse: str = "",
):
	item_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
	mr_doc = frappe.get_doc(
		{
			"doctype": "Material Request",
			"material_request_type": material_request_type,
			"company": company,
			"transaction_date": nowdate(),
			"schedule_date": add_days(nowdate(), 1),
			"customer": customer if material_request_type == "Customer Provided" else "",
			"set_warehouse": set_warehouse or "",
			"set_from_warehouse": set_from_warehouse or "",
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"uom": item_uom,
					"stock_uom": item_uom,
					"conversion_factor": 1,
					"schedule_date": add_days(nowdate(), 1),
					"warehouse": warehouse,
					"from_warehouse": from_warehouse or "",
					"cost_center": cost_center,
					"bom_no": bom_no or "",
				}
			],
		}
	).insert(ignore_permissions=True)
	if mr_doc.docstatus != 1:
		mr_doc.submit()
	mr_doc.reload()
	return mr_doc


def _ensure_transit_warehouse(*, company: str, run_id: str) -> str:
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)

	transit_warehouse = frappe.db.get_value(
		"Warehouse",
		{"company": company, "warehouse_type": "Transit"},
		"name",
	)
	if not transit_warehouse:
		transit_warehouse = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"Transit {run_id}",
					"warehouse_type": "Transit",
					"company": company,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	if not frappe.db.get_value("Company", company, "default_in_transit_warehouse"):
		frappe.db.set_value(
			"Company",
			company,
			"default_in_transit_warehouse",
			transit_warehouse,
			update_modified=False,
		)
	return transit_warehouse
