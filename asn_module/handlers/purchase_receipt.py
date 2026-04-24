import json

import frappe
from frappe import _
from frappe.utils import flt

from asn_module.traceability import emit_asn_item_transition


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
	# Prefill supplier-facing transport/invoice references on PR draft.
	pr.supplier_delivery_note = asn.supplier_invoice_no
	pr.transporter_name = asn.transporter_name
	pr.lr_no = asn.lr_no
	pr.lr_date = asn.lr_date

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

	for asn_item in asn.items:
		emit_asn_item_transition(
			asn=asn.name,
			asn_item=asn_item.name,
			item_code=asn_item.item_code,
			state="PR_CREATED_DRAFT",
			transition_status="OK",
			ref_doctype="Purchase Receipt",
			ref_name=pr.name,
		)

	return {
		"doctype": "Purchase Receipt",
		"name": pr.name,
		"url": f"/app/purchase-receipt/{pr.name}",
		"message": _("Purchase Receipt {0} created from ASN {1}").format(pr.name, source_name),
	}


def on_purchase_receipt_submit(doc, method):
	"""Update ASN receipt tracking and attach follow-up QR codes on submit."""
	del method

	if doc.asn:
		asn = frappe.get_doc("ASN", doc.asn)
		asn_items_map = json.loads(doc.asn_items or "{}")
		received_qty_by_asn_item = {}

		for pr_item in doc.items:
			mapping = asn_items_map.get(str(pr_item.idx))
			if not mapping:
				continue

			asn_item_name = mapping.get("asn_item_name")
			if not asn_item_name:
				continue
			received_qty_by_asn_item[asn_item_name] = received_qty_by_asn_item.get(asn_item_name, 0) + flt(
				pr_item.qty
			)

		for asn_item_name, qty_delta in received_qty_by_asn_item.items():
			frappe.db.sql(
				"""
				UPDATE `tabASN Item`
				SET received_qty = COALESCE(received_qty, 0) + %s
				WHERE name = %s
				""",
				(qty_delta, asn_item_name),
			)

		asn.reload()
		asn.update_receipt_status()

		asn_item_codes = {
			row.name: row.item_code
			for row in frappe.get_all(
				"ASN Item",
				filters={"name": ["in", list(received_qty_by_asn_item)]},
				fields=["name", "item_code"],
			)
		}

		for asn_item_name in received_qty_by_asn_item:
			emit_asn_item_transition(
				asn=asn.name,
				asn_item=asn_item_name,
				item_code=asn_item_codes.get(asn_item_name),
				state="PR_SUBMITTED",
				transition_status="OK",
				ref_doctype="Purchase Receipt",
				ref_name=doc.name,
			)
