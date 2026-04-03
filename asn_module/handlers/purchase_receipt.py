import json

import frappe
from frappe import _


def create_from_asn(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Purchase Receipt from a submitted ASN."""
	del source_doctype, payload

	asn = frappe.get_doc("ASN", source_name)
	if asn.docstatus != 1:
		frappe.throw(_("Purchase Receipt can only be created from a submitted ASN"))
	if asn.status in ("Received", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot create Purchase Receipt from ASN {0} with status {1}").format(source_name, asn.status)
		)

	existing_pr = frappe.db.get_value("Purchase Receipt", {"asn": source_name, "docstatus": 0}, "name")
	if existing_pr:
		return {
			"doctype": "Purchase Receipt",
			"name": existing_pr,
			"url": f"/app/purchase-receipt/{existing_pr}",
			"message": _("Existing draft Purchase Receipt {0} opened").format(existing_pr),
		}

	asn_items_map = {}
	pr = frappe.new_doc("Purchase Receipt")
	pr.supplier = asn.supplier
	pr.asn = asn.name

	for asn_item in asn.items:
		pr_item = pr.append(
			"items",
			{
				"item_code": asn_item.item_code,
				"item_name": asn_item.item_name,
				"qty": asn_item.qty,
				"uom": asn_item.uom,
				"rate": asn_item.rate,
				"batch_no": asn_item.batch_no,
				"serial_no": asn_item.serial_nos,
				"purchase_order": asn_item.purchase_order,
				"purchase_order_item": asn_item.purchase_order_item,
			},
		)
		asn_items_map[str(pr_item.idx)] = {
			"asn_item_name": asn_item.name,
			"original_qty": asn_item.qty,
		}

	pr.asn_items = json.dumps(asn_items_map)
	pr.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Receipt",
		"name": pr.name,
		"url": f"/app/purchase-receipt/{pr.name}",
		"message": _("Purchase Receipt {0} created from ASN {1}").format(pr.name, source_name),
	}


def on_purchase_receipt_submit(doc, method):
	"""Update ASN receipt tracking and attach follow-up QR codes on submit."""
	del method

	if not doc.asn:
		return

	asn = frappe.get_doc("ASN", doc.asn)
	asn_items_map = json.loads(doc.asn_items or "{}")

	for pr_item in doc.items:
		mapping = asn_items_map.get(str(pr_item.idx))
		if not mapping:
			continue

		for asn_item in asn.items:
			if asn_item.name != mapping["asn_item_name"]:
				continue
			asn_item.received_qty = (asn_item.received_qty or 0) + pr_item.qty
			break

	asn.update_receipt_status()

	from asn_module.qr_engine.generate import generate_qr

	purchase_invoice_qr = generate_qr(
		action="create_purchase_invoice",
		source_doctype="Purchase Receipt",
		source_name=doc.name,
	)
	_attach_qr_to_doc(doc, purchase_invoice_qr, "purchase-invoice-qr")

	putaway_required = False
	for pr_item in doc.items:
		inspection_required = frappe.db.get_value(
			"Item", pr_item.item_code, "inspection_required_before_purchase"
		)
		if inspection_required:
			continue
		putaway_required = True

	if putaway_required:
		putaway_qr = generate_qr(
			action="confirm_putaway",
			source_doctype="Purchase Receipt",
			source_name=doc.name,
		)
		_attach_qr_to_doc(doc, putaway_qr, f"putaway-{doc.name}")


def _attach_qr_to_doc(doc, qr_result, prefix):
	"""Attach a generated QR image to the target document."""
	import base64

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
