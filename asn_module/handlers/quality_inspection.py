import frappe
from frappe import _

from asn_module.handlers.utils import attach_qr_to_doc


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

	from asn_module.qr_engine.generate import generate_qr

	qr_result = generate_qr(
		action=action,
		source_doctype="Quality Inspection",
		source_name=doc.name,
	)
	_attach_qr_to_doc(doc, qr_result, action)
	frappe.msgprint(message, alert=True)


def _attach_qr_to_doc(doc, qr_result, prefix):
	"""Attach a generated QR image to the target document."""
	attach_qr_to_doc(doc, qr_result, prefix)
