import base64

import frappe
from frappe import _
from frappe.utils import today


def fiscal_year_for_date(date: str) -> str | None:
	"""The enabled Fiscal Year that covers ``date``, if the site defines one."""
	return frappe.db.get_value(
		"Fiscal Year",
		{"disabled": 0, "year_start_date": ("<=", date), "year_end_date": (">=", date)},
		"name",
	)


def fill_custom_fiscal_year(doc) -> None:
	"""Satisfy a site's mandatory Fiscal Year on a document the scan chain builds.

	Sites mark a ``custom_fiscal_year`` Link mandatory on receipts and invoices.
	A desk form fills it for a desk user, but the scan chain builds these documents
	server-side, where no form ever runs, and the insert then dies on the missing
	mandatory field. Fill it from the document's own posting date. No-op where the
	doctype does not carry the field or does not require it. A value that names a
	Fiscal Year this site actually has is kept; one that does not (a field default
	left behind by a fiscal-year rollover) is replaced, so a stale default cannot
	break the scan chain.
	"""
	meta = getattr(doc, "meta", None)
	field = meta.get_field("custom_fiscal_year") if meta else None
	if not field or not field.reqd:
		return
	existing = (doc.get("custom_fiscal_year") or "").strip()
	if existing and frappe.db.exists("Fiscal Year", existing):
		return
	date = doc.get("posting_date") or doc.get("transaction_date") or today()
	fiscal_year = fiscal_year_for_date(date)
	if fiscal_year:
		doc.custom_fiscal_year = fiscal_year


def attach_qr_to_doc(doc, qr_result, prefix):
	"""Attach a generated QR image to the target document."""
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{prefix}-{doc.name}.png",
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"content": base64.b64decode(qr_result["image_base64"]),
			"is_private": 0,
		}
	).save(ignore_permissions=True)


def attach_scan_codes_to_doc(doc, action: str, prefix: str) -> None:
	"""Attach the QR and barcode that create this document's successor.

	Both images carry one scan code: ``get_or_create_scan_code`` shares a
	registry row per (action, source) pair, so a QR scan and a barcode scan
	of the same printed document dispatch the same action.
	"""
	from asn_module.qr_engine.generate import generate_barcode, generate_qr

	qr_result = generate_qr(action=action, source_doctype=doc.doctype, source_name=doc.name)
	attach_qr_to_doc(doc, qr_result, f"{prefix}-qr")
	barcode_result = generate_barcode(action=action, source_doctype=doc.doctype, source_name=doc.name)
	attach_qr_to_doc(doc, barcode_result, f"{prefix}-barcode")


def find_pr_row_for_qi(qi, purchase_receipt):
	"""Resolve the Purchase Receipt row a Quality Inspection refers to.

	Prefers the explicit ``purchase_receipt_item`` link; falls back to a single item-code
	match, throws if ambiguous or missing.
	"""
	qi_pr_item = getattr(qi, "purchase_receipt_item", None)
	if qi_pr_item:
		for item in purchase_receipt.items:
			if item.name == qi_pr_item:
				return item

	matching_rows = [item for item in purchase_receipt.items if item.item_code == qi.item_code]
	if len(matching_rows) == 1:
		return matching_rows[0]
	if len(matching_rows) > 1:
		frappe.throw(
			_(
				"Multiple Purchase Receipt rows found for item {0} in {1}. "
				"Set a specific purchase_receipt_item on Quality Inspection {2}."
			).format(qi.item_code, qi.reference_name, qi.name)
		)

	frappe.throw(_("Item {0} not found in {1}").format(qi.item_code, qi.reference_name))
