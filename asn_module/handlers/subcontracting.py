import frappe
from frappe import _

from asn_module.handlers.utils import fill_custom_fiscal_year, store_scan_code
from asn_module.qr_engine.scan_codes import void_scan_codes

SUBCONTRACTING_RECEIPT_ACTION_FROM_DISPATCH = "create_subcontracting_receipt_from_dispatch"
SUBCONTRACTING_RECEIPT_PR_ACTION = "create_purchase_receipt_from_subcontracting_receipt"


def create_dispatch_from_subcontracting_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Send to Subcontractor Stock Entry from a submitted SCO."""
	del source_doctype, payload

	sco = frappe.get_doc("Subcontracting Order", source_name)
	if sco.docstatus != 1:
		frappe.throw(_("Subcontracting Order {0} must be submitted").format(source_name))

	from erpnext.controllers.subcontracting_controller import make_rm_stock_entry

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry = make_rm_stock_entry(
		sco.name,
		order_doctype="Subcontracting Order",
		target_doc=stock_entry,
	)
	stock_entry.insert(ignore_permissions=True)

	return {
		"doctype": "Stock Entry",
		"name": stock_entry.name,
		"url": f"/app/stock-entry/{stock_entry.name}",
		"message": _("Stock Entry {0} (Send to Subcontractor) created from {1}").format(
			stock_entry.name, source_name
		),
	}


def create_receipt_from_subcontracting_order(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Subcontracting Receipt from a submitted SCO."""
	del source_doctype, payload

	sco = frappe.get_doc("Subcontracting Order", source_name)
	if sco.docstatus != 1:
		frappe.throw(_("Subcontracting Order {0} must be submitted").format(source_name))

	from erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order import (
		make_subcontracting_receipt,
	)

	scr = make_subcontracting_receipt(sco.name)
	fill_custom_fiscal_year(scr)
	scr.insert(ignore_permissions=True)

	return {
		"doctype": "Subcontracting Receipt",
		"name": scr.name,
		"url": f"/app/subcontracting-receipt/{scr.name}",
		"message": _("Subcontracting Receipt {0} created from {1}").format(scr.name, source_name),
	}


def create_receipt_from_subcontracting_dispatch(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Subcontracting Receipt from a submitted Send to Subcontractor entry.

	The entry's own code names the entry, not its order, so resolve the order here.
	"""
	del source_doctype

	stock_entry = frappe.get_doc("Stock Entry", source_name)
	if stock_entry.docstatus != 1:
		frappe.throw(_("Stock Entry {0} must be submitted").format(source_name))
	if stock_entry.stock_entry_type != "Send to Subcontractor" or not stock_entry.subcontracting_order:
		frappe.throw(_("Stock Entry {0} is not a Send to Subcontractor entry").format(source_name))

	return create_receipt_from_subcontracting_order(
		"Subcontracting Order", stock_entry.subcontracting_order, payload
	)


def create_receipt_from_subcontracting_receipt(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Purchase Receipt from a submitted Subcontracting Receipt.

	The finished goods the supplier returned are received into stock through
	a Purchase Receipt; the invoice for that receipt is raised from it in turn,
	never from the Subcontracting Receipt itself.
	"""
	del source_doctype, payload

	scr = frappe.get_doc("Subcontracting Receipt", source_name)
	if scr.docstatus != 1:
		frappe.throw(_("Subcontracting Receipt {0} must be submitted").format(source_name))
	if getattr(scr, "is_return", 0):
		frappe.throw(_("A subcontracting return does not create a Purchase Receipt."))

	existing = frappe.db.get_value(
		"Purchase Receipt",
		{"subcontracting_receipt": scr.name, "docstatus": 0},
		"name",
	)
	if existing:
		return {
			"doctype": "Purchase Receipt",
			"name": existing,
			"url": f"/app/purchase-receipt/{existing}",
			"message": _("Existing draft Purchase Receipt {0} opened").format(existing),
		}

	from erpnext.subcontracting.doctype.subcontracting_receipt.subcontracting_receipt import (
		make_purchase_receipt,
	)

	pr = make_purchase_receipt(scr.name)
	fill_custom_fiscal_year(pr)
	pr.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Receipt",
		"name": pr.name,
		"url": f"/app/purchase-receipt/{pr.name}",
		"message": _("Purchase Receipt {0} created from Subcontracting Receipt {1}").format(
			pr.name, scr.name
		),
	}


def on_subcontracting_receipt_submit(doc, method=None):
	"""Store the Purchase Receipt scan code when a Subcontracting Receipt is submitted."""
	del method
	if getattr(doc, "is_return", 0):
		return
	store_scan_code(doc, SUBCONTRACTING_RECEIPT_PR_ACTION)


def on_subcontracting_receipt_cancel(doc, method=None):
	"""Void the receipt scan code so a cancelled receipt cannot be scanned."""
	del method
	void_scan_codes(SUBCONTRACTING_RECEIPT_PR_ACTION, "Subcontracting Receipt", doc.name)


def on_subcontracting_order_submit(doc, method):
	"""Store the dispatch scan code when a Subcontracting Order is submitted."""
	del method

	store_scan_code(doc, "create_subcontracting_dispatch")


def on_subcontracting_order_cancel(doc, method=None):
	"""Void the dispatch scan code so a cancelled order cannot be scanned."""
	del method
	void_scan_codes("create_subcontracting_dispatch", "Subcontracting Order", doc.name)


def on_subcontracting_dispatch_submit(doc, method):
	"""Store the receipt scan code when a Send to Subcontractor Stock Entry is submitted."""
	del method

	if doc.stock_entry_type != "Send to Subcontractor" or not doc.subcontracting_order:
		return

	store_scan_code(doc, SUBCONTRACTING_RECEIPT_ACTION_FROM_DISPATCH)


def on_subcontracting_dispatch_cancel(doc, method=None):
	"""Void the receipt scan code so a cancelled Send to Subcontractor entry cannot be scanned."""
	del method

	# Runs on every Stock Entry cancel; only a dispatch ever stored this code.
	if doc.stock_entry_type != "Send to Subcontractor" or not doc.subcontracting_order:
		return

	void_scan_codes(SUBCONTRACTING_RECEIPT_ACTION_FROM_DISPATCH, "Stock Entry", doc.name)
