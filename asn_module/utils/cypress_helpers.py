import frappe
from frappe import _
from frappe.utils import flt


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

	single_po = create_purchase_order(
		qty=1,
		supplier=supplier.name,
		item_count=100,
		rate=10,
		unique_items=True,
	)
	bulk_po = create_purchase_order(
		qty=1,
		supplier=supplier.name,
		item_count=100,
		rate=10,
		unique_items=True,
	)
	return {
		"supplier": supplier.name,
		"portal_user": portal_user_name,
		"portal_password": portal_password,
		"single_purchase_order": {
			"name": single_po.name,
			"items": [i.as_dict() for i in single_po.items],
		},
		"bulk_purchase_order": {
			"name": bulk_po.name,
			"items": [i.as_dict() for i in bulk_po.items],
		},
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


@frappe.whitelist()
def seed_stock_cap_context():
	"""Seed a branch with one cap warehouse and an item capped below the PO quantity.

	Returns everything the stock cap spec needs to drive the desk form.
	"""
	if not frappe.conf.get("allow_tests"):
		frappe.throw(_("Only available in test mode"))
	frappe.only_for("System Manager")

	branch = "_Cypress Cap Branch"
	if not frappe.db.exists("Branch", branch):
		frappe.get_doc({"doctype": "Branch", "branch": branch}).insert(ignore_permissions=True)

	supplier, _portal_user_name, _portal_password = _ensure_supplier_portal_user(
		supplier_name="Test Supplier E2E",
		portal_email="supplier_e2e@test.com",
		portal_password="supplier_e2e",
	)

	# Build the PO directly with build_purchase_order_with_mandatory_fields rather than
	# going through seed_supplier_context(): some benches (this one included) import
	# Property Setters/Custom Fields from a production-like setup that make
	# `custom_order_type` and a `taxes` row mandatory on Purchase Order, which the plain
	# create_purchase_order() fixture used by seed_supplier_context() does not populate.
	# build_purchase_order_with_mandatory_fields() fills them in only when the current
	# site's metadata actually requires them, so this keeps working on a clean CI bench
	# too (see asn_module/utils/test_setup.py and TestASNStockCap.setUp() for the same
	# pattern used by this app's own test suite).
	from asn_module.asn_module.doctype.asn.test_asn import _ensure_company, create_purchase_order
	from asn_module.utils.test_setup import build_purchase_order_with_mandatory_fields

	# Dedicated item + warehouse, distinct from every other nightly seeder's fixtures.
	# seed_minimal_asn/seed_scan_station_context (used by asn_desk_nightly.js,
	# asn_portal_nightly.js and scan_station_nightly.js) submit ASNs against the shared
	# default item/warehouse and never complete a Purchase Receipt, so those ASNs stay
	# docstatus=1 for the life of the site. stock_cap/fetch.py's _fetch_in_transit sums
	# *all* submitted, unreceived ASN Items for an item+warehouse with no branch/PO
	# filter, so if this seeder reused that default item/warehouse, CI's full nightly
	# run (no --spec filter, alphabetically after those three specs) would attribute
	# their leftover in-transit stock to this branch's cap and break test 1. Using our
	# own item/warehouse, seeded fresh here, structurally makes that impossible.
	item_code = "_Cypress Cap Item"
	if not frappe.db.exists("Item", item_code):
		item_doc = {
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": frappe.db.get_value("Item Group", {}, "name") or "All Item Groups",
			"stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
			"inspection_required_before_purchase": 0,
		}
		# On benches with india_compliance installed, a fresh Item with no HSN/SAC code
		# fails Item.validate whenever GST Settings.validate_hsn_code is on (the default
		# is_sales_item=1 routes every new Item through that check). This seeder is a live
		# whitelisted RPC endpoint with no enclosing test transaction, so it must not reach
		# for disable_hsn_validation() -- that helper mutates GST Settings site-wide with no
		# rollback outside a FrappeTestCase's setUpClass (see its docstring in
		# asn_module/utils/test_setup.py). Instead, satisfy the validation on its own merits
		# by pointing at an existing GST HSN Code record, when that field/doctype exists.
		# Fail open: skip silently on a bench without india_compliance (the real CI bench).
		if frappe.db.has_column("Item", "gst_hsn_code"):
			existing_hsn_code = frappe.db.get_value("GST HSN Code", {}, "name")
			if existing_hsn_code:
				item_doc["gst_hsn_code"] = existing_hsn_code
		frappe.get_doc(item_doc).insert(ignore_permissions=True)

	company = _ensure_company()
	abbr = frappe.get_cached_value("Company", company, "abbr")
	warehouse_short_name = "_Cypress Cap Warehouse"
	warehouse = f"{warehouse_short_name} - {abbr}"
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_short_name,
				"company": company,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	po = build_purchase_order_with_mandatory_fields(
		create_purchase_order,
		tax_description="asn_module stock cap e2e",
		qty=10,
		supplier=supplier.name,
		item_code=item_code,
		warehouse=warehouse,
	)
	purchase_order = po.name
	frappe.db.set_value("Purchase Order", purchase_order, "branch", branch)

	po_item = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=["name", "item_code", "warehouse", "qty"],
		limit=1,
	)[0]

	frappe.db.delete("ASN Stock Cap Warehouse", {"warehouse": po_item.warehouse})
	if frappe.db.exists("ASN Stock Cap Settings", branch):
		frappe.delete_doc("ASN Stock Cap Settings", branch, force=True)

	frappe.get_doc(
		{
			"doctype": "ASN Stock Cap Settings",
			"branch": branch,
			"enabled": 1,
			"warehouses": [{"warehouse": po_item.warehouse}],
		}
	).insert(ignore_permissions=True)

	# Cap at half the PO quantity, so a quarter-quantity ASN never breaches. The e2e spec
	# drives the "passing" and "breaching" ASNs against this *same* purchase order back to
	# back and submits the passing one first, which consumes `passing_qty` of the PO's
	# receivable quantity (see asn.py's "exceeds remaining PO qty" check). So breaching_qty
	# can't just be the full PO quantity -- by the time the breaching ASN is saved, only
	# `po_item.qty - passing_qty` (= 3/4 of the PO qty) is still receivable. 0.6x the PO
	# quantity clears the cap (> 0.5x) while staying inside that remaining receivable
	# quantity (< 0.75x).
	frappe.db.set_value("Item", po_item.item_code, "custom_max_stock", flt(po_item.qty) / 2)

	return {
		"branch": branch,
		"supplier": supplier.name,
		"purchase_order": purchase_order,
		"item_code": po_item.item_code,
		"warehouse": po_item.warehouse,
		"breaching_qty": flt(po_item.qty) * 0.6,
		"passing_qty": flt(po_item.qty) / 4,
	}
