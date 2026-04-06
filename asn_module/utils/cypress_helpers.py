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
