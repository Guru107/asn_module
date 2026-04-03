import base64

import frappe


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
