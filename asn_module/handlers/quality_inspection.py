import frappe
from frappe import _

from asn_module.handlers.utils import attach_scan_codes_to_doc


def on_quality_inspection_submit(doc, method):
	"""Attach the next QR action for accepted or rejected Quality Inspections."""
	del method

	if doc.reference_type != "Purchase Receipt":
		return

	if doc.status == "Accepted":
		action = "create_stock_transfer"
		message = _("Stock Transfer QR attached for Quality Inspection {0}").format(doc.name)
	elif doc.status == "Rejected":
		action = "create_purchase_return"
		message = _("Purchase Return QR attached for Quality Inspection {0}").format(doc.name)
	else:
		return

	attach_scan_codes_to_doc(doc, action)
	frappe.msgprint(message, alert=True)
