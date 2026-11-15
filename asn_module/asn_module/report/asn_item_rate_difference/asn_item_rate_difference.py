# Copyright (c) 2026, Gurudatt Kulkarni and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Abs
from frappe.utils import getdate

from asn_module.rate_difference import RATE_EPSILON, build_rate_difference_rows

SCOPE_FILTERS = ("asn", "supplier", "purchase_order", "supplier_invoice_no", "from_date", "to_date")


def execute(filters=None):
	filters = filters or {}
	frappe.has_permission("ASN", "report", throw=True)
	if not any(filters.get(key) for key in SCOPE_FILTERS):
		frappe.throw(_("Set at least one filter (ASN, Supplier, Purchase Order, Invoice No or date)."))
	rows = build_rate_difference_rows(_rate_rows(filters))
	return _columns(), rows


def _columns():
	return [
		{"label": _("ASN"), "fieldname": "asn", "fieldtype": "Link", "options": "ASN", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 160,
		},
		{
			"label": _("Supplier Invoice No"),
			"fieldname": "supplier_invoice_no",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 150,
		},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 140,
		},
		{"label": _("ASN Item"), "fieldname": "asn_item", "fieldtype": "Data", "width": 140},
		{"label": _("ASN Rate"), "fieldname": "asn_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("PO Rate"), "fieldname": "po_rate", "fieldtype": "Currency", "width": 110},
		{
			"label": _("Rate Difference"),
			"fieldname": "rate_difference",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{
			"label": _("Amount Difference"),
			"fieldname": "amount_difference",
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def _rate_rows(filters: dict) -> list[dict]:
	asn_item = DocType("ASN Item")
	asn = DocType("ASN")
	po_item = DocType("Purchase Order Item")
	query = (
		frappe.qb.from_(asn_item)
		.inner_join(asn)
		.on(asn.name == asn_item.parent)
		.inner_join(po_item)
		.on(po_item.name == asn_item.purchase_order_item)
		.select(
			asn.name.as_("asn"),
			asn.status,
			asn.supplier,
			asn.supplier_invoice_no,
			asn_item.purchase_order,
			asn_item.item_code,
			asn_item.name.as_("asn_item"),
			asn_item.rate.as_("asn_rate"),
			po_item.rate.as_("po_rate"),
			asn_item.qty,
		)
		.where(asn.docstatus != 2)
		.where(Abs(asn_item.rate - po_item.rate) > RATE_EPSILON)
		.orderby(asn.name)
		.orderby(asn_item.idx)
	)
	if filters.get("asn"):
		query = query.where(asn.name == filters["asn"])
	if filters.get("supplier"):
		query = query.where(asn.supplier == filters["supplier"])
	if filters.get("purchase_order"):
		query = query.where(asn_item.purchase_order == filters["purchase_order"])
	if filters.get("supplier_invoice_no"):
		query = query.where(asn.supplier_invoice_no == filters["supplier_invoice_no"])
	if filters.get("from_date"):
		query = query.where(asn.asn_date >= getdate(filters["from_date"]))
	if filters.get("to_date"):
		query = query.where(asn.asn_date <= getdate(filters["to_date"]))
	return query.run(as_dict=True)
