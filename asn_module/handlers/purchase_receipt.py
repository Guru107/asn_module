import json

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.utils import cint, flt

from asn_module.handlers.utils import attach_qr_to_doc
from asn_module.stock_cap.api import breaches_for_purchase_receipt
from asn_module.stock_cap.fetch import EXCLUDED_ASN_STATUSES
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

	if _is_job_asn(asn):
		if _gate_pass_mode_on():
			return _open_or_create_job_gate_pass(asn)
		return _open_or_create_subcontracting_receipt(asn)

	existing_pr = frappe.db.get_value("Purchase Receipt", {"asn": source_name, "docstatus": 0}, "name")
	if existing_pr:
		return {
			"doctype": "Purchase Receipt",
			"name": existing_pr,
			"url": f"/app/purchase-receipt/{existing_pr}",
			"message": _("Existing draft Purchase Receipt {0} opened").format(existing_pr),
		}

	if _gate_pass_mode_on():
		return _open_or_create_material_gate_pass(asn)

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

	Filling skips the same statuses in-transit ignores (Received and Closed). A Closed
	shipment can still have unreceived quantity; recording it there would leave the open
	shipment in transit. Cancel also skips Closed, so a closed shipment this receipt did
	not fill is not reduced. It still sees Received: filling an open shipment moves it to
	Received, and cancel has to reverse that.
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
		SELECT ai.name, ai.parent, ai.purchase_order_item, ai.qty, ai.received_qty, asn.status
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
		# Fill skips Received and Closed. Cancel skips Closed only: the shipment this
		# receipt filled is Received by the time cancel runs.
		skipped = EXCLUDED_ASN_STATUSES if sign > 0 else ("Closed",)
		rows = [row for row in rows if row.status not in skipped]
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
	A return is a separate transaction: the quantity that arrived stays received, so
	cancelling the return does not change it either.
	"""
	del method
	if getattr(doc, "is_return", 0):
		return
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


def _gate_pass_mode_on() -> bool:
	if not frappe.db.exists("DocType", "ASN Settings"):
		return False
	return cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode")) == 1


def _set_if_present(doc, fieldname: str, value) -> None:
	if value is None or not doc.meta.has_field(fieldname):
		return
	doc.set(fieldname, value)


def _ensure_gate_pass_asn_link() -> None:
	if frappe.db.has_column("Gate Pass", "asn"):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Gate Pass": [
				{
					"fieldname": "asn",
					"fieldtype": "Link",
					"label": "ASN",
					"options": "ASN",
					"insert_after": "supplier",
				}
			]
		}
	)
	frappe.clear_cache(doctype="Gate Pass")


def _open_or_create_material_gate_pass(asn) -> dict:
	"""Save a draft Gate Pass for a Material ASN and open it.

	A non-cancelled Gate Pass for this ASN is reopened. A cancelled one is ignored.
	"""
	existing = _reopen_uncancelled_gate_pass(asn)
	if existing:
		return existing

	purchase_order_name, _purchase_order_items = _get_single_purchase_order(asn)
	purchase_order = frappe.get_doc("Purchase Order", purchase_order_name)
	order_lines = {row.name: row for row in purchase_order.items}

	gate_pass = frappe.new_doc("Gate Pass")
	_set_if_present(gate_pass, "entry_type", "Gate In")
	_set_if_present(gate_pass, "gate_pass_type", "Material")
	_set_if_present(gate_pass, "document_reference", "Purchase Order")
	_set_if_present(gate_pass, "reference_number", purchase_order.name)
	_set_if_present(gate_pass, "company", purchase_order.company)
	_set_if_present(gate_pass, "supplier", asn.supplier)
	_set_if_present(gate_pass, "vehicle_number", asn.vehicle_number)
	_set_if_present(gate_pass, "invoice_number", asn.supplier_invoice_no)
	_set_if_present(gate_pass, "invoice_date", asn.supplier_invoice_date)
	_set_if_present(gate_pass, "asn", asn.name)

	invoice_no = (asn.supplier_invoice_no or "").strip()
	invoices_field = gate_pass.meta.get_field("gate_pass_invoices")
	if invoices_field and invoices_field.fieldtype == "Table" and invoice_no:
		invoice_fields = {df.fieldname for df in frappe.get_meta(invoices_field.options).fields}
		invoice_row = {}
		if "supplier_delivery_note" in invoice_fields:
			invoice_row["supplier_delivery_note"] = invoice_no
		if "invoice_date" in invoice_fields:
			invoice_row["invoice_date"] = asn.supplier_invoice_date
		gate_pass.append("gate_pass_invoices", invoice_row)

	for items_fieldname, items_field in _gate_pass_line_tables(gate_pass):
		child_fields = {df.fieldname for df in frappe.get_meta(items_field.options).fields}
		for asn_item in asn.items:
			order_line = order_lines.get(asn_item.purchase_order_item)
			shipped_qty = flt(asn_item.qty)
			row = {}
			if "item_code" in child_fields:
				row["item_code"] = asn_item.item_code
			if "uom" in child_fields:
				row["uom"] = asn_item.uom
			if "rate" in child_fields:
				row["rate"] = asn_item.rate
			if "purchase_order_item" in child_fields:
				row["purchase_order_item"] = asn_item.purchase_order_item
			if "order_item_name" in child_fields:
				row["order_item_name"] = asn_item.purchase_order_item
			if "supplier_delivery_note" in child_fields and invoice_no:
				row["supplier_delivery_note"] = invoice_no
			if "receive_qty" in child_fields:
				row["receive_qty"] = shipped_qty
			if "received_qty" in child_fields:
				row["received_qty"] = shipped_qty
			if order_line and "qty" in child_fields:
				row["qty"] = flt(order_line.qty)
			if order_line and "ordered_qty" in child_fields:
				row["ordered_qty"] = flt(order_line.qty)
			if order_line and "pending_qty" in child_fields:
				row["pending_qty"] = flt(order_line.qty) - flt(getattr(order_line, "received_qty", 0))
			gate_pass.append(items_fieldname, row)

	gate_pass.insert(ignore_permissions=True)

	return {
		"doctype": "Gate Pass",
		"name": gate_pass.name,
		"url": f"/app/gate-pass/{gate_pass.name}",
		"message": _("Gate Pass {0} created from ASN {1}").format(gate_pass.name, asn.name),
	}


def _open_or_create_job_gate_pass(asn) -> dict:
	"""Save a draft Gate In of type Job for one Subcontracting Order and open it.

	Arriving qty on each line is the Shipped Qty. A cancelled Gate Pass is ignored.
	"""
	existing = _reopen_uncancelled_gate_pass(asn)
	if existing:
		return existing

	order_name = next(row.subcontracting_order for row in asn.items if row.subcontracting_order)
	order = frappe.get_doc("Subcontracting Order", order_name)
	order_lines = {row.name: row for row in order.items}

	gate_pass = frappe.new_doc("Gate Pass")
	_set_if_present(gate_pass, "entry_type", "Gate In")
	_set_if_present(gate_pass, "gate_pass_type", "Job")
	_set_if_present(gate_pass, "document_reference", "Subcontracting Order")
	_set_if_present(gate_pass, "reference_number", order.name)
	_set_if_present(gate_pass, "company", order.company)
	_set_if_present(gate_pass, "supplier", asn.supplier)
	_set_if_present(gate_pass, "vehicle_number", asn.vehicle_number)
	_set_if_present(gate_pass, "invoice_number", asn.supplier_invoice_no)
	_set_if_present(gate_pass, "invoice_date", asn.supplier_invoice_date)
	_set_if_present(gate_pass, "asn", asn.name)

	table_field, child_fields = _job_line_table(gate_pass)
	if table_field:
		for asn_item in asn.items:
			if not asn_item.subcontracting_order_item:
				continue
			order_line = order_lines.get(asn_item.subcontracting_order_item)
			row = {}
			if "item_code" in child_fields:
				row["item_code"] = asn_item.item_code
			if "subcontracting_order_item" in child_fields:
				row["subcontracting_order_item"] = asn_item.subcontracting_order_item
			if "qty" in child_fields:
				row["qty"] = flt(asn_item.qty)
			if order_line and "pending_qty" in child_fields:
				row["pending_qty"] = flt(order_line.qty) - flt(getattr(order_line, "received_qty", 0))
			gate_pass.append(table_field, row)

	gate_pass.flags.ignore_validate = True
	gate_pass.insert(ignore_permissions=True, ignore_mandatory=True)

	return {
		"doctype": "Gate Pass",
		"name": gate_pass.name,
		"url": f"/app/gate-pass/{gate_pass.name}",
		"message": _("Gate Pass {0} created from ASN {1}").format(gate_pass.name, asn.name),
	}


def _reopen_uncancelled_gate_pass(asn) -> dict | None:
	if not frappe.db.exists("DocType", "Gate Pass"):
		frappe.throw(_("Gate Pass is not set up on this site."))

	_ensure_gate_pass_asn_link()
	existing = frappe.get_all(
		"Gate Pass",
		filters={"asn": asn.name, "docstatus": ["!=", 2]},
		pluck="name",
		order_by="modified desc",
		limit=1,
	)
	if not existing:
		return None
	name = existing[0]
	return {
		"doctype": "Gate Pass",
		"name": name,
		"url": f"/app/gate-pass/{name}",
		"message": _("Existing Gate Pass {0} opened").format(name),
	}


def _job_line_table(gate_pass) -> tuple[str | None, set[str]]:
	"""The child table Create copies onto a Subcontracting Receipt.

	Staging keeps job lines on ``item``. A site that only has ``items`` still
	receives the lines when that table can name a Subcontracting Order line.
	"""
	for fieldname in ("item", "items"):
		field = gate_pass.meta.get_field(fieldname)
		if not field or field.fieldtype != "Table":
			continue
		child_fields = {df.fieldname for df in frappe.get_meta(field.options).fields}
		if fieldname == "item" or "subcontracting_order_item" in child_fields:
			return fieldname, child_fields
	return None, set()


@frappe.whitelist()
def create_receipt_from_gate_pass(gate_pass_name: str) -> dict:
	"""Open the draft receipt for a submitted Gate Pass. The scan does not call this.

	A Material Gate In becomes a Purchase Receipt that still carries the ASN.
	A Job Gate In becomes a Subcontracting Receipt linked to the ASN.
	"""
	gate_pass = frappe.get_doc("Gate Pass", gate_pass_name)
	if cint(gate_pass.docstatus) != 1:
		frappe.throw(_("Submit the Gate Pass before creating a receipt."))

	if _is_job_gate_pass(gate_pass):
		return _create_subcontracting_receipt_from_gate_pass(gate_pass)
	return _create_purchase_receipt_from_gate_pass(gate_pass)


def _is_job_gate_pass(gate_pass) -> bool:
	if (getattr(gate_pass, "gate_pass_type", None) or "") == "Job":
		return True
	return (getattr(gate_pass, "document_reference", None) or "") == "Subcontracting Order"


def _create_purchase_receipt_from_gate_pass(gate_pass) -> dict:
	asn = frappe.get_doc("ASN", gate_pass.asn)
	purchase_order_items = [row.purchase_order_item for row in asn.items if row.purchase_order_item]
	pr = make_purchase_receipt(
		gate_pass.reference_number or asn.items[0].purchase_order,
		args={"filtered_children": purchase_order_items},
	)
	_apply_asn_fields(pr, asn)
	_set_if_present(pr, "custom_gate_pass_reference", gate_pass.name)
	pr.insert(ignore_permissions=True)
	return {
		"doctype": "Purchase Receipt",
		"name": pr.name,
		"url": f"/app/purchase-receipt/{pr.name}",
		"message": _("Purchase Receipt {0} created from Gate Pass {1}").format(pr.name, gate_pass.name),
	}


def _create_subcontracting_receipt_from_gate_pass(gate_pass) -> dict:
	asn = frappe.get_doc("ASN", gate_pass.asn)
	result = _open_or_create_subcontracting_receipt(asn)
	receipt = frappe.get_doc("Subcontracting Receipt", result["name"])
	if _apply_gate_pass_qty_to_subcontracting_receipt(receipt, gate_pass):
		receipt.save(ignore_permissions=True)
	return result


def _apply_gate_pass_qty_to_subcontracting_receipt(receipt, gate_pass) -> bool:
	"""Copy arriving qty from the Job Gate Pass ``item`` lines onto the receipt."""
	qty_by_line = {}
	for row in gate_pass.get("item") or []:
		line_name = getattr(row, "subcontracting_order_item", None)
		if line_name and flt(row.qty) > 0:
			qty_by_line[line_name] = flt(row.qty)
	if not qty_by_line:
		return False
	changed = False
	for item in receipt.items:
		qty = qty_by_line.get(item.subcontracting_order_item)
		if qty is None:
			continue
		item.qty = qty
		item.received_qty = qty
		item.amount = flt(qty) * flt(item.rate)
		changed = True
	return changed


def stamp_receipt_built_by_gate_pass(doc, method=None) -> None:
	"""Stamp the ASN onto a receipt the Gate Pass Create action has already mapped.

	Create sets ``custom_gate_pass_reference`` before insert. This runs then, so the
	stores button keeps the ASN, supplier invoice, lorry receipt, batch, and serial.
	"""
	del method
	if getattr(doc, "asn", None):
		return
	gate_pass_name = doc.get("custom_gate_pass_reference")
	if not gate_pass_name or not frappe.db.exists("DocType", "Gate Pass"):
		return
	if not frappe.db.has_column("Gate Pass", "asn"):
		return
	asn_name = frappe.db.get_value("Gate Pass", gate_pass_name, "asn")
	if not asn_name:
		return
	if doc.doctype == "Purchase Receipt":
		_apply_asn_fields(doc, frappe.get_doc("ASN", asn_name))
		return
	doc.asn = asn_name


def _gate_pass_line_tables(gate_pass) -> list[tuple[str, object]]:
	"""Child tables that hold material lines.

	Sites that use the Gate Entry app store lines on ``gate_pass_table``. The
	scan fixture uses ``items``. A site can have both, and each one is filled.
	"""
	tables = []
	for fieldname in ("gate_pass_table", "items"):
		field = gate_pass.meta.get_field(fieldname)
		if field and field.fieldtype == "Table":
			tables.append((fieldname, field))
	return tables


def _is_job_asn(asn) -> bool:
	for row in getattr(asn, "items", None) or []:
		if (getattr(row, "subcontracting_order", None) or "").strip():
			return True
	return False


def _open_or_create_subcontracting_receipt(asn) -> dict:
	"""Draft Subcontracting Receipt for a Job ASN. Finished-good qty is the Shipped Qty.

	Used when Gate Pass Mode is off, and when Create runs on a submitted Job Gate Pass.
	A later call opens the same draft.
	"""
	from asn_module.custom_fields.subcontracting_receipt import setup as setup_scr_asn_link

	if not frappe.db.has_column("Subcontracting Receipt", "asn"):
		setup_scr_asn_link()

	existing = frappe.db.get_value(
		"Subcontracting Receipt",
		{"asn": asn.name, "docstatus": 0},
		"name",
	)
	if existing:
		return {
			"doctype": "Subcontracting Receipt",
			"name": existing,
			"url": f"/app/subcontracting-receipt/{existing}",
			"message": _("Existing draft Subcontracting Receipt {0} opened").format(existing),
		}

	order_name = next(row.subcontracting_order for row in asn.items if row.subcontracting_order)
	mapped_items = [
		{"name": row.subcontracting_order_item, "qty": flt(row.qty)}
		for row in asn.items
		if row.subcontracting_order_item
	]
	from erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order import (
		make_subcontracting_receipt,
	)

	previous_args = getattr(frappe.flags, "args", None)
	frappe.flags.args = frappe._dict(items=mapped_items)
	try:
		receipt = make_subcontracting_receipt(order_name)
	finally:
		frappe.flags.args = previous_args

	_apply_shipped_qty_to_subcontracting_receipt(receipt, asn)
	receipt.asn = asn.name
	receipt.insert(ignore_permissions=True)

	return {
		"doctype": "Subcontracting Receipt",
		"name": receipt.name,
		"url": f"/app/subcontracting-receipt/{receipt.name}",
		"message": _("Subcontracting Receipt {0} created from ASN {1}").format(receipt.name, asn.name),
	}


def _apply_shipped_qty_to_subcontracting_receipt(receipt, asn) -> None:
	pending: dict[str, list] = {}
	for row in asn.items:
		if not row.subcontracting_order_item:
			continue
		pending.setdefault(row.subcontracting_order_item, []).append(row)

	for receipt_item in receipt.items:
		matches = pending.get(receipt_item.subcontracting_order_item) or []
		asn_item = matches.pop(0) if matches else None
		if not asn_item:
			continue
		receipt_item.qty = flt(asn_item.qty)
		receipt_item.received_qty = flt(asn_item.qty)
		# Shipped Qty is the finished-good quantity on the receipt. ERPNext may already
		# have split a process-loss percentage out of the mapped qty; that split would
		# no longer match the quantity the supplier shipped.
		if hasattr(receipt_item, "process_loss_qty"):
			receipt_item.process_loss_qty = 0
		receipt_item.amount = flt(receipt_item.qty) * flt(receipt_item.rate)


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
	"""Update ASN receipt tracking and attach follow-up QR codes on submit.

	A return does not record against the ASN. The supplier's shipment already arrived;
	sending some of it back is its own transaction and leaves ``received_qty`` as it is.
	"""
	del method
	if getattr(doc, "is_return", 0):
		return

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
