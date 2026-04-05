import frappe
from frappe import _

from asn_module.handlers.utils import attach_qr_to_doc
from asn_module.qr_engine.generate import generate_qr


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
	scr.insert(ignore_permissions=True)

	return {
		"doctype": "Subcontracting Receipt",
		"name": scr.name,
		"url": f"/app/subcontracting-receipt/{scr.name}",
		"message": _("Subcontracting Receipt {0} created from {1}").format(scr.name, source_name),
	}


def on_subcontracting_order_submit(doc, method):
	"""Generate dispatch QR when a Subcontracting Order is submitted."""
	del method

	qr_result = generate_qr(
		action="create_subcontracting_dispatch",
		source_doctype="Subcontracting Order",
		source_name=doc.name,
	)
	attach_qr_to_doc(doc, qr_result, "subcontracting-dispatch-qr")


def on_subcontracting_dispatch_submit(doc, method):
	"""Generate receipt QR when Send to Subcontractor Stock Entry is submitted."""
	del method

	if doc.stock_entry_type != "Send to Subcontractor" or not doc.subcontracting_order:
		return

	qr_result = generate_qr(
		action="create_subcontracting_receipt",
		source_doctype="Subcontracting Order",
		source_name=doc.subcontracting_order,
	)
	attach_qr_to_doc(doc, qr_result, "subcontracting-receipt-qr")
