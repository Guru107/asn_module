import json

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.utils import flt

from asn_module.handlers.utils import attach_qr_to_doc
from asn_module.stock_cap.api import breaches_for_purchase_receipt
from asn_module.stock_cap.messages import throw_stock_cap_exceeded
from asn_module.stock_cap.precision import flt_qty
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


def _po_conversion_factors(po_item_names: list[str]) -> dict[str, float]:
	names = [name for name in po_item_names if name]
	if not names:
		return {}
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"name": ["in", names]},
		fields=["name", "conversion_factor"],
		limit_page_length=0,
	)
	return {row.name: flt(row.conversion_factor) for row in rows}


def _delivered_purchase_qty(row, po_factor: float | None) -> float:
	"""Quantity this receipt row delivers, in the Purchase Order line's UOM.

	``ASN Item.qty`` and ``received_qty`` are both in that UOM. A receipt can use a
	different UOM, so ``qty + rejected_qty`` is only right when the units already match.
	When the row carries ``stock_qty`` and a Purchase Order Item, convert stock units
	back through the PO conversion factor. Rows without those fields keep the historical
	``qty + rejected_qty`` sum.
	"""
	rejected = flt(getattr(row, "rejected_qty", 0))
	stock_qty = getattr(row, "stock_qty", None)
	po_item = getattr(row, "purchase_order_item", None)
	if stock_qty is not None and po_item:
		factor = flt(po_factor)
		if factor <= 0:
			factor = 1.0
		receipt_factor = flt(getattr(row, "conversion_factor", 0))
		if receipt_factor <= 0:
			receipt_factor = 1.0
		return (flt(stock_qty) + rejected * receipt_factor) / factor
	return flt(getattr(row, "qty", 0)) + rejected


def _add_received_qty(asn_item_name: str, delta: float) -> None:
	delta = flt_qty(delta)
	if not delta:
		return
	frappe.db.sql(
		"""
		UPDATE `tabASN Item`
		SET received_qty = GREATEST(COALESCE(received_qty, 0) + %s, 0)
		WHERE name = %s
		""",
		(delta, asn_item_name),
	)


def _lines_with_delivered_qty(doc) -> list[tuple]:
	"""Receipt rows paired with the purchase-UOM quantity each one delivers."""
	items = getattr(doc, "items", None) or []
	factors = _po_conversion_factors([getattr(row, "purchase_order_item", None) for row in items])
	return [
		(row, _delivered_purchase_qty(row, factors.get(getattr(row, "purchase_order_item", None))))
		for row in items
	]


def _record_linked_received_qty(doc, sign: int) -> tuple[list[str], bool]:
	"""Apply delivered qty for mapped rows.

	Returns the mapped ASN Item names, in first-seen order, and whether any quantity was
	written. Submit uses the names for transitions; cancel refreshes the ASN only when a
	quantity changed.
	"""
	mapping = json.loads(getattr(doc, "asn_items", None) or "{}")
	received_qty_by_asn_item: dict[str, float] = {}
	mapped_names: dict[str, None] = {}
	for pr_item, delivered in _lines_with_delivered_qty(doc):
		asn_item_name = (mapping.get(str(pr_item.idx)) or {}).get("asn_item_name")
		if not asn_item_name:
			continue
		mapped_names.setdefault(asn_item_name, None)
		if delivered:
			received_qty_by_asn_item[asn_item_name] = (
				received_qty_by_asn_item.get(asn_item_name, 0.0) + delivered
			)

	for asn_item_name, qty in received_qty_by_asn_item.items():
		_add_received_qty(asn_item_name, sign * qty)

	return list(mapped_names), bool(received_qty_by_asn_item)


def _record_unlinked_received_qty(doc, sign: int) -> list[str]:
	"""Spread a receipt that has no ASN link across the submitted ASN lines for its PO items.

	The standard Purchase Order -> Create -> Purchase Receipt action leaves ``asn`` empty,
	so the linked mapping never runs and ``received_qty`` stays 0. In-transit keeps the
	full ASN quantity after the goods are already on hand.
	"""
	delivered_by_po_item: dict[str, float] = {}
	for row, delivered in _lines_with_delivered_qty(doc):
		po_item = getattr(row, "purchase_order_item", None)
		if not po_item or delivered <= 0:
			continue
		delivered_by_po_item[po_item] = delivered_by_po_item.get(po_item, 0.0) + delivered

	if not delivered_by_po_item:
		return []

	po_items = list(delivered_by_po_item)
	# Only the placeholder run is interpolated. Every purchase order item name is a param.
	placeholders = ", ".join(["%s"] * len(po_items))
	asn_rows = frappe.db.sql(
		"""
		SELECT ai.name, ai.parent, ai.purchase_order_item, ai.qty, ai.received_qty
		FROM `tabASN Item` ai
		INNER JOIN `tabASN` asn ON asn.name = ai.parent AND asn.docstatus = 1
		WHERE ai.purchase_order_item IN ("""
		+ placeholders
		+ """
		)
		ORDER BY ai.parent, ai.idx
		""",
		po_items,
		as_dict=True,
	)
	rows_by_po_item: dict[str, list] = {}
	for row in asn_rows:
		rows_by_po_item.setdefault(row.purchase_order_item, []).append(row)

	parents: set[str] = set()
	for po_item, delivered in delivered_by_po_item.items():
		rows = rows_by_po_item.get(po_item) or []
		remaining = delivered
		# Submit fills lines in document order. Cancel subtracts in reverse so a single
		# receipt restores the lines it filled. Several receipts on one PO item can
		# leave the remainder on a different line; the total received quantity, which
		# the cap uses, still changes by the cancelled amount.
		ordered = rows if sign > 0 else list(reversed(rows))
		for index, row in enumerate(ordered):
			if remaining <= 0:
				break
			if sign > 0:
				room = max(flt(row.qty) - flt(row.received_qty), 0)
				take = remaining if index == len(ordered) - 1 else min(room, remaining)
			else:
				take = min(flt(row.received_qty), remaining)
			if take <= 0:
				continue
			_add_received_qty(row.name, sign * take)
			parents.add(row.parent)
			remaining -= take

	return sorted(parents)


def _refresh_asn_receipt_status(asn_names: list[str]) -> None:
	for asn_name in asn_names:
		if not asn_name or not frappe.db.exists("ASN", asn_name):
			continue
		asn = frappe.get_doc("ASN", asn_name)
		asn.update_receipt_status()


def on_purchase_receipt_cancel(doc, method=None):
	"""Put delivered quantity back when a receipt is cancelled.

	Submit adds to ``ASN Item.received_qty`` and may mark the ASN Received, which drops
	it out of in-transit. Cancel reverses the stock ledger and must reverse that too.
	A return is included: its quantity is negative, so submit and cancel swap direction.
	"""
	del method
	if getattr(doc, "asn", None):
		_mapped, updated = _record_linked_received_qty(doc, sign=-1)
		asn_names = [doc.asn] if updated else []
	else:
		asn_names = _record_unlinked_received_qty(doc, sign=-1)
	_refresh_asn_receipt_status(asn_names)


def on_purchase_receipt_before_submit(doc, method=None):
	"""Block a receipt that would carry an item above its branch maximum.

	Runs before_submit so no stock ledger entry is written before the block. The Purchase
	Order Items this receipt is itself receiving are excluded from the in-transit figure
	inside breaches_for_purchase_receipt, whether or not this receipt is linked back to an
	ASN by name.
	"""
	breaches = breaches_for_purchase_receipt(doc)
	if not breaches:
		return

	throw_stock_cap_exceeded(breaches)


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
	if not getattr(pr, "supplier_name", None):
		pr.supplier_name = getattr(asn, "supplier_name", None) or asn.supplier
	pr.title = pr.supplier_name or pr.supplier
	pr.asn = asn.name
	# ASN owns supplier-facing transport/invoice references.
	pr.supplier_delivery_note = asn.supplier_invoice_no
	pr.transporter_name = asn.transporter_name
	pr.vehicle_no = asn.vehicle_number
	pr.driver_name = asn.driver_contact
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

	if doc.asn:
		mapped_names, _updated = _record_linked_received_qty(doc, sign=1)
	else:
		_refresh_asn_receipt_status(_record_unlinked_received_qty(doc, sign=1))
		return

	asn = frappe.get_doc("ASN", doc.asn)
	asn.reload()
	asn.update_receipt_status()

	if not mapped_names:
		return

	asn_item_codes = {
		row.name: row.item_code
		for row in frappe.get_all(
			"ASN Item",
			filters={"name": ["in", mapped_names]},
			fields=["name", "item_code"],
		)
	}

	for asn_item_name in mapped_names:
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
