import frappe
from frappe.website.utils import cleanup_page_name


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.title = "ASN"

	user = frappe.session.user
	context.can_create_asn = frappe.has_permission("ASN", "create", user=user)
	supplier = _get_supplier_for_user(user)

	if not supplier:
		context.asn_list = []
		return

	asn_list = frappe.get_all(
		"ASN",
		filters={"supplier": supplier, "docstatus": ("!=", 2)},
		fields=["name", "route", "supplier_invoice_no", "status", "expected_delivery_date", "asn_date"],
		order_by="creation desc",
		limit_page_length=50,
	)

	item_counts = {
		row.parent: row.total_items
		for row in frappe.get_all(
			"ASN Item",
			filters={"parent": ["in", [asn.name for asn in asn_list]]},
			fields=["parent", "count(name) as total_items"],
			group_by="parent",
		)
	}

	for asn in asn_list:
		if not asn.route:
			asn.route = _ensure_asn_route(asn.name)
		asn.total_items = item_counts.get(asn.name, 0)

	context.asn_list = asn_list


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
