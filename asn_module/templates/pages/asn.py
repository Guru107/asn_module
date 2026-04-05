import frappe
from frappe import _
from frappe.website.utils import cleanup_page_name

from asn_module.supplier_asn_portal import purchase_receipt_exists_for_asn


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.title = "ASN"

	user = frappe.session.user
	supplier = _get_supplier_for_user(user)
	context.can_create_asn = bool(supplier)

	if not supplier:
		context.asn_list = []
		return

	asn_list = frappe.get_all(
		"ASN",
		filters={"supplier": supplier, "docstatus": ("!=", 2)},
		fields=[
			"name",
			"route",
			"supplier_invoice_no",
			"status",
			"expected_delivery_date",
			"asn_date",
			"docstatus",
		],
		order_by="creation desc",
		limit_page_length=50,
	)

	asns_with_pr = set()
	if asn_list:
		for row in frappe.get_all(
			"Purchase Receipt",
			filters={"asn": ["in", [a.name for a in asn_list]], "docstatus": ("!=", 2)},
			fields=["asn"],
		):
			if row.asn:
				asns_with_pr.add(row.asn)

	item_counts = {
		row.parent: row.total_items
		for row in frappe.get_all(
			"ASN Item",
			filters={"parent": ["in", [asn.name for asn in asn_list]]},
			fields=["parent", {"COUNT": "name", "as": "total_items"}],
			group_by="parent",
		)
	}

	for asn in asn_list:
		if not asn.route:
			asn.route = _ensure_asn_route(asn.name)
		asn.total_items = item_counts.get(asn.name, 0)
		asn.can_cancel_portal = (
			asn.docstatus == 1 and asn.status == "Submitted" and asn.name not in asns_with_pr
		)

	context.asn_list = asn_list


def get_open_purchase_orders_for_supplier(supplier: str) -> list[frappe._dict]:
	if not supplier:
		return []

	return frappe.get_all(
		"Purchase Order",
		filters={
			"supplier": supplier,
			"docstatus": 1,
			"status": ["in", ["To Receive", "To Receive and Bill"]],
		},
		fields=["name", "transaction_date", "schedule_date", "status"],
		order_by="transaction_date desc",
		limit_page_length=200,
	)


def _get_supplier_for_user(user):
	if user == "Administrator":
		return None

	return frappe.db.get_value(
		"Portal User",
		{"user": user, "parenttype": "Supplier"},
		"parent",
	)


def has_website_permission(doc, ptype, user=None, verbose=False):
	del ptype, verbose

	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	supplier = _get_supplier_for_user(user)
	return doc.supplier == supplier if supplier else False


def _ensure_asn_route(asn_name: str) -> str:
	route = f"asn/{cleanup_page_name(asn_name).replace('_', '-')}"
	frappe.db.set_value("ASN", asn_name, "route", route, update_modified=False)
	return route


@frappe.whitelist(methods=["POST"])
def cancel_portal_asn(asn_name: str | None = None):
	"""Cancel a submitted ASN for the logged-in portal supplier, if no purchase receipt exists."""
	asn_name = (asn_name or "").strip()
	if not asn_name:
		frappe.throw(_("ASN is required."))

	supplier = _get_supplier_for_user(frappe.session.user)
	if not supplier:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc = frappe.get_doc("ASN", asn_name)
	if doc.supplier != supplier:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if doc.docstatus != 1:
		frappe.throw(_("Only submitted notices can be cancelled from the portal."))

	if doc.status != "Submitted":
		frappe.throw(
			_(
				"This notice cannot be cancelled from the portal in its current state. "
				"Contact your buyer if you need help."
			)
		)

	if purchase_receipt_exists_for_asn(doc.name):
		frappe.throw(
			_(
				"A purchase receipt already exists for this notice, so it cannot be cancelled here. "
				"Contact your buyer if the shipment was created by mistake."
			)
		)

	doc.flags.ignore_permissions = True
	doc.cancel()

	return {"ok": True, "redirect": "/asn"}
