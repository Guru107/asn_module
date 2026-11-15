import json

import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as make_purchase_invoice_from_pr,
)
from frappe import _
from frappe.utils import cint, flt

from asn_module.handlers.purchase_receipt import refuse_qty_declared_on_open_asns
from asn_module.handlers.utils import fill_custom_fiscal_year
from asn_module.traceability import emit_asn_item_transition


def create_from_purchase_receipt(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Purchase Invoice from a submitted Purchase Receipt."""
	del source_doctype, payload

	pr = frappe.get_doc("Purchase Receipt", source_name)
	if pr.docstatus != 1:
		frappe.throw(
			_("Purchase Receipt {0} must be submitted before creating a Purchase Invoice").format(pr.name)
		)

	if flt(pr.per_billed) >= 100:
		frappe.throw(_("Purchase Receipt {0} is already fully billed").format(pr.name))

	existing_pi = frappe.db.get_value(
		"Purchase Invoice Item",
		{"purchase_receipt": pr.name, "docstatus": 0},
		"parent",
	)
	if existing_pi:
		return {
			"doctype": "Purchase Invoice",
			"name": existing_pi,
			"url": f"/app/purchase-invoice/{existing_pi}",
			"message": _("Existing draft Purchase Invoice {0} opened").format(existing_pi),
		}

	asn = frappe.get_doc("ASN", pr.asn) if pr.asn else None

	pi = make_purchase_invoice_from_pr(pr.name)
	pi.asn = pr.asn
	if asn:
		pi.bill_no = asn.supplier_invoice_no
		pi.bill_date = asn.supplier_invoice_date
	fill_custom_fiscal_year(pi)
	pi.insert(ignore_permissions=True)

	if pr.asn:
		asn_items_map = json.loads(pr.asn_items or "{}")
		for pr_item in pr.items:
			mapping = asn_items_map.get(pr_item.name)
			if not mapping:
				continue
			emit_asn_item_transition(
				asn=pr.asn,
				asn_item=mapping.get("asn_item_name"),
				item_code=pr_item.item_code,
				state="PI_CREATED_DRAFT",
				transition_status="OK",
				ref_doctype="Purchase Invoice",
				ref_name=pi.name,
			)

	return {
		"doctype": "Purchase Invoice",
		"name": pi.name,
		"url": f"/app/purchase-invoice/{pi.name}",
		"message": _("Purchase Invoice {0} created from Purchase Receipt {1}").format(pi.name, pr.name),
	}


def on_purchase_invoice_before_submit(doc, method=None):
	"""Refuse a stock-updating invoice row that takes quantity an open ASN declares.

	Such a row receives goods the way a receipt with no ASN link does. A row billed against
	a Purchase Receipt is skipped: that receipt brought the goods in and was checked then.
	"""
	del method
	if not cint(doc.get("update_stock")) or cint(doc.get("is_return")):
		return
	refuse_qty_declared_on_open_asns(
		[
			frappe._dict(
				idx=row.idx,
				purchase_order_item=row.po_detail,
				qty=flt(row.qty),
				rejected_qty=flt(row.get("rejected_qty")),
				stock_qty=row.get("stock_qty"),
				conversion_factor=row.get("conversion_factor"),
			)
			for row in doc.items or []
			if row.get("po_detail") and not row.get("purchase_receipt")
		]
	)
