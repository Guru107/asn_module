import base64

import frappe
from frappe import _


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
