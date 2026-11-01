import json
from types import SimpleNamespace

import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as make_purchase_invoice_from_pr,
)
from frappe import _
from frappe.utils import cint, flt

from asn_module.handlers.utils import apply_site_document_requirements
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
	apply_site_document_requirements(pi)
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


def on_purchase_invoice_submit(doc, method=None):
	"""Record a stock-updating invoice on open shipments the way an unlinked receipt does."""
	del method
	_record_stock_invoice_on_open_shipments(doc, sign=1)


def on_purchase_invoice_cancel(doc, method=None):
	"""Reverse the received quantity a stock-updating invoice added to open shipments."""
	del method
	_record_stock_invoice_on_open_shipments(doc, sign=-1)


def _record_stock_invoice_on_open_shipments(doc, sign: int) -> None:
	if not cint(doc.get("update_stock")) or cint(doc.get("is_return")):
		return

	from asn_module.handlers.purchase_receipt import (
		_record_unlinked_received_qty,
		_refresh_asn_receipt_status,
	)

	parents = _record_unlinked_received_qty(_invoice_lines_not_against_a_receipt(doc), sign=sign)
	_refresh_asn_receipt_status(parents)


def _invoice_lines_not_against_a_receipt(doc):
	"""Purchase Invoice rows shaped like an unlinked receipt, in purchase UOM.

	A row billed against a Purchase Receipt is skipped. That receipt already recorded
	Received Qty, and counting the invoice as well would consume the shipment twice.
	"""
	items = []
	for row in doc.items or []:
		if row.get("purchase_receipt"):
			continue
		po_item = row.get("po_detail")
		if not po_item:
			continue
		items.append(
			frappe._dict(
				purchase_order_item=po_item,
				qty=flt(row.qty),
				rejected_qty=flt(row.get("rejected_qty")),
				stock_qty=row.get("stock_qty"),
				conversion_factor=row.get("conversion_factor"),
			)
		)
	return SimpleNamespace(items=items)
