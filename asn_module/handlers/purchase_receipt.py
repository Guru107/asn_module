import json

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.utils import flt

from asn_module.handlers.utils import attach_qr_to_doc
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

	purchase_order, purchase_order_items = _get_single_purchase_order(asn)
	pr = make_purchase_receipt(purchase_order, args={"filtered_children": purchase_order_items})
	_apply_asn_fields(pr, asn)

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


def _get_single_purchase_order(asn) -> tuple[str, list[str]]:
	purchase_orders = {asn_item.purchase_order for asn_item in asn.items if asn_item.purchase_order}
	if not purchase_orders:
		frappe.throw(_("ASN {0} must reference a Purchase Order").format(asn.name))
	if len(purchase_orders) > 1:
		frappe.throw(_("ASN {0} can reference only one Purchase Order").format(asn.name))

	purchase_order_items = _unique(
		[asn_item.purchase_order_item for asn_item in asn.items if asn_item.purchase_order_item]
	)
	if not purchase_order_items:
		frappe.throw(_("ASN {0} must reference Purchase Order Items").format(asn.name))

	return purchase_orders.pop(), purchase_order_items


def _unique(values: list[str]) -> list[str]:
	return list(dict.fromkeys(values))


def _apply_asn_fields(pr, asn) -> None:
	pr.supplier = asn.supplier
	pr.asn = asn.name
	# ASN owns supplier-facing transport/invoice references.
	pr.supplier_delivery_note = asn.supplier_invoice_no
	pr.transporter_name = asn.transporter_name
	pr.lr_no = asn.lr_no
	pr.lr_date = asn.lr_date

	_preserve_asn_item_rows(pr, asn.items)
	asn_items_by_po_item = {}
	for asn_item in asn.items:
		asn_items_by_po_item.setdefault(asn_item.purchase_order_item, []).append(asn_item)

	asn_items_map = {}
	for pr_item in pr.items:
		matching_asn_items = asn_items_by_po_item.get(pr_item.purchase_order_item) or []
		asn_item = matching_asn_items.pop(0) if matching_asn_items else None
		if not asn_item:
			continue

		pr_item.qty = flt(asn_item.qty)
		pr_item.stock_qty = flt(asn_item.qty) * flt(pr_item.conversion_factor or 1)
		pr_item.batch_no = asn_item.batch_no
		pr_item.serial_no = asn_item.serial_nos
		_set_amounts_from_qty(pr, pr_item)
		asn_items_map[str(pr_item.idx)] = {
			"asn_item_name": asn_item.name,
			"original_qty": asn_item.qty,
		}

	pr.asn_items = json.dumps(asn_items_map)


def _preserve_asn_item_rows(pr, asn_items) -> None:
	if len(pr.items) == len(asn_items):
		return

	item_templates = {
		pr_item.purchase_order_item: _as_child_row_dict(pr_item)
		for pr_item in pr.items
		if pr_item.purchase_order_item
	}
	pr.set("items", [])
	for asn_item in asn_items:
		template = item_templates.get(asn_item.purchase_order_item)
		if template:
			pr.append("items", template)


def _as_child_row_dict(row) -> dict:
	values = row.as_dict() if hasattr(row, "as_dict") else vars(row).copy()
	for fieldname in (
		"name",
		"parent",
		"parentfield",
		"parenttype",
		"idx",
		"doctype",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
	):
		values.pop(fieldname, None)
	return values


def _set_amounts_from_qty(pr, pr_item) -> None:
	amount = flt(pr_item.qty) * flt(pr_item.rate)
	base_amount = amount * flt(pr.conversion_rate or 1)
	pr_item.amount = amount
	pr_item.base_amount = base_amount
	if hasattr(pr_item, "net_amount"):
		pr_item.net_amount = amount
	if hasattr(pr_item, "base_net_amount"):
		pr_item.base_net_amount = base_amount


def on_purchase_receipt_trash(doc, method):
	"""Remove draft-creation trace rows so stale draft PRs can be deleted."""
	del method

	if doc.docstatus != 0:
		return

	frappe.db.delete(
		"ASN Transition Log",
		{
			"ref_doctype": "Purchase Receipt",
			"ref_name": doc.name,
			"state": "PR_CREATED_DRAFT",
		},
	)
	frappe.db.delete(
		"Scan Log",
		{
			"action": "create_purchase_receipt",
			"result_doctype": "Purchase Receipt",
			"result_name": doc.name,
			"result": "Success",
		},
	)
	if doc.asn:
		frappe.db.set_value(
			"Scan Code",
			{
				"action_key": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": doc.asn,
				"status": "Used",
			},
			"status",
			"Active",
			update_modified=True,
		)


def on_purchase_receipt_submit(doc, method):
	"""Update ASN receipt tracking and attach follow-up QR codes on submit."""
	del method

	if not doc.asn:
		return

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

	from asn_module.qr_engine.generate import generate_qr

	purchase_invoice_qr = generate_qr(
		action="create_purchase_invoice",
		source_doctype="Purchase Receipt",
		source_name=doc.name,
	)
	attach_qr_to_doc(doc, purchase_invoice_qr, "purchase-invoice-qr")

	putaway_required = any(
		not frappe.get_cached_value("Item", pr_item.item_code, "inspection_required_before_purchase")
		for pr_item in doc.items
	)

	if putaway_required:
		putaway_qr = generate_qr(
			action="confirm_putaway",
			source_doctype="Purchase Receipt",
			source_name=doc.name,
		)
		attach_qr_to_doc(doc, putaway_qr, f"putaway-{doc.name}")
