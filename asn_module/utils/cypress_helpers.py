import frappe
from frappe import _


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

	from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

	po1 = create_purchase_order(qty=10, supplier=supplier.name)
	po2 = create_purchase_order(qty=5, supplier=supplier.name)

	return {
		"supplier": supplier.name,
		"portal_user": portal_user.name,
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

	from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

	po = create_purchase_order(qty=1, supplier=supplier.name, item_count=100, rate=10)
	return {
		"supplier": supplier.name,
		"portal_user": portal_user.name,
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
