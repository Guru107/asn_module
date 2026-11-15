import json
from types import SimpleNamespace

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import cint, flt

from asn_module.handlers.gate_pass_create import gate_pass_receive_qty
from asn_module.handlers.utils import (
	fill_custom_fiscal_year,
	store_scan_code,
)
from asn_module.qr_engine.scan_codes import void_scan_codes
from asn_module.stock_cap.api import breaches_for_purchase_receipt
from asn_module.stock_cap.messages import throw_stock_cap_exceeded
from asn_module.stock_cap.precision import flt_qty
from asn_module.traceability import emit_asn_item_transition

ASN_PURCHASE_RECEIPT_SCAN_ACTION = "create_purchase_receipt"
ASN_GATE_PASS_SCAN_ACTION = "create_gate_pass_from_asn"


def asn_dispatch_action_key() -> str:
	"""Label stamped on a submitted ASN's QR; handlers still read Gate Pass Mode at scan time."""
	if _gate_pass_mode_on():
		return ASN_GATE_PASS_SCAN_ACTION
	return ASN_PURCHASE_RECEIPT_SCAN_ACTION


def _load_submitted_asn_for_scan(source_name: str):
	asn = frappe.get_doc("ASN", source_name)
	if asn.docstatus != 1:
		frappe.throw(_("Purchase Receipt can only be created from a submitted ASN"))
	if asn.status in ("Received", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot create Purchase Receipt from ASN {0} with status {1}").format(source_name, asn.status)
		)
	return asn


def create_gate_pass_from_asn(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Open or create a draft Gate Pass from a submitted ASN when Gate Pass Mode is on.

	When the mode is off, the same printed code follows the direct receipt path so a
	toggle after the ASN was submitted does not strand barcodes.
	"""
	del source_doctype, payload

	asn = _load_submitted_asn_for_scan(source_name)
	if not _gate_pass_mode_on():
		return _create_receipt_from_asn(asn, source_name)
	return _open_gate_pass_from_asn(asn, source_name)


def _open_existing_draft_purchase_receipt_for_asn(asn_name: str) -> dict | None:
	existing_pr = frappe.db.get_value("Purchase Receipt", {"asn": asn_name, "docstatus": 0}, "name")
	if not existing_pr:
		return None
	return {
		"doctype": "Purchase Receipt",
		"name": existing_pr,
		"url": f"/app/purchase-receipt/{existing_pr}",
		"message": _("Existing draft Purchase Receipt {0} opened").format(existing_pr),
	}


def _open_gate_pass_from_asn(asn, source_name: str) -> dict:
	if _is_job_asn(asn):
		return _open_or_create_job_gate_pass(asn)

	existing = _open_existing_draft_purchase_receipt_for_asn(source_name)
	if existing:
		return existing

	return _open_or_create_material_gate_pass(asn)


def _create_receipt_from_asn(asn, source_name: str) -> dict:
	if _is_job_asn(asn):
		return _open_or_create_subcontracting_receipt(asn)

	existing = _open_existing_draft_purchase_receipt_for_asn(source_name)
	if existing:
		return existing

	purchase_order, purchase_order_items = _get_single_purchase_order(asn)
	pr = make_purchase_receipt(purchase_order, args={"filtered_children": purchase_order_items})
	_apply_asn_fields(pr, asn)
	fill_custom_fiscal_year(pr)

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
		asn_item_name = (mapping.get(pr_item.name) or {}).get("asn_item_name")
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


def refuse_qty_declared_on_open_asns(items: list) -> None:
	"""Refuse receipt rows with no ASN link that take quantity an open ASN still declares.

	Such a row may receive at most its PO line's Remaining Qty as it stood before this
	document: the part no open ASN covers, within the over-receipt allowance. Past that the
	goods overlap a shipment in transit, so they must be received by scanning that ASN. An
	excess no ASN covers is left to ERPNext's own over-receipt check.
	"""
	delivered_by_po_item: dict[str, float] = {}
	row_idxs_by_po_item: dict[str, list[str]] = {}
	for row, delivered in _lines_with_delivered_qty(SimpleNamespace(items=items)):
		po_item = getattr(row, "purchase_order_item", None)
		if not po_item:
			continue
		delivered_by_po_item[po_item] = delivered_by_po_item.get(po_item, 0.0) + delivered
		row_idxs_by_po_item.setdefault(po_item, []).append(str(row.idx))
	if not delivered_by_po_item:
		return

	# Imported here: asn.py imports this module.
	from asn_module.asn_module.doctype.asn.asn import remaining_qty_by_purchase_order_item

	po_lines = {
		line.name: line
		for line in frappe.get_all(
			"Purchase Order Item",
			filters={"name": ["in", list(delivered_by_po_item)]},
			fields=["name", "parent", "idx", "item_code", "qty"],
		)
	}
	remaining_by_po_item = remaining_qty_by_purchase_order_item(
		{name: flt(line.qty) for name, line in po_lines.items()}
	)
	excess_by_po_item = {}
	for po_item, delivered in delivered_by_po_item.items():
		remaining = remaining_by_po_item.get(po_item)
		# None is a unit-price line with no cap: it has no ceiling to exceed.
		if remaining is None:
			continue
		excess = flt_qty(delivered - flt(remaining))
		if excess > 0:
			excess_by_po_item[po_item] = excess
	if not excess_by_po_item:
		return

	messages = []
	for po_item, asns in _unreceived_qty_on_open_asns(list(excess_by_po_item)).items():
		line = po_lines[po_item]
		declared = flt_qty(min(excess_by_po_item[po_item], sum(qty for _asn, qty in asns)))
		asn_names = ", ".join(asn for asn, _qty in asns)
		messages.append(
			_(
				"Row {0}: {1} of {2} on {3} row {4} is already declared on {5}; receive it by scanning {5}"
			).format(
				", ".join(row_idxs_by_po_item[po_item]),
				declared,
				line.item_code,
				line.parent,
				line.idx,
				asn_names,
			)
		)
	if messages:
		frappe.throw("<br>".join(messages), title=_("Quantity Declared on an Open ASN"))


def _unreceived_qty_on_open_asns(po_items: list[str]) -> dict[str, list[tuple[str, float]]]:
	"""Unreceived Shipped Qty per ASN for each PO Item, on the ASNs Remaining Qty holds back."""
	asn_item = frappe.qb.DocType("ASN Item")
	asn = frappe.qb.DocType("ASN")
	received = IfNull(asn_item.received_qty, 0)
	rows = (
		frappe.qb.from_(asn_item)
		.inner_join(asn)
		.on(asn.name == asn_item.parent)
		.select(asn_item.purchase_order_item, asn.name.as_("asn"), Sum(asn_item.qty - received).as_("qty"))
		.where(asn_item.purchase_order_item.isin(po_items))
		.where(asn.docstatus != 2)
		.where(asn.status != "Closed")
		.where(asn_item.qty > received)
		.groupby(asn_item.purchase_order_item, asn.name)
		.orderby(asn.name)
	).run(as_dict=True)
	by_po_item: dict[str, list[tuple[str, float]]] = {}
	for row in rows:
		by_po_item.setdefault(row.purchase_order_item, []).append((row.asn, flt(row.qty)))
	return by_po_item


def on_purchase_receipt_cancel(doc, method=None):
	"""Put delivered quantity back when a receipt is cancelled.

	Submit adds to ``ASN Item.received_qty`` and may mark the ASN Received, which drops
	it out of in-transit. Cancel reverses the stock ledger and must reverse that too.
	A return is a separate transaction: the quantity that arrived stays received, so
	cancelling the return does not change it either. A receipt with no ASN link never
	touched an ASN, so cancelling it leaves every ASN as it is.
	"""
	del method
	if getattr(doc, "is_return", 0) or not getattr(doc, "asn", None):
		return
	_mapped, updated = _record_linked_received_qty(doc, sign=-1)
	if updated and frappe.db.exists("ASN", doc.asn):
		frappe.get_doc("ASN", doc.asn).update_receipt_status()


def on_purchase_receipt_before_submit(doc, method=None):
	"""Block a receipt that would carry an item above its branch maximum.

	Runs before_submit so no stock ledger entry is written before the block. The Purchase
	Order Items this receipt is itself receiving are excluded from the in-transit figure
	inside breaches_for_purchase_receipt when this receipt is linked to an ASN.

	A receipt with no ASN link may only take quantity no open ASN declares.
	"""
	_pair_unmapped_rows(doc)
	if not getattr(doc, "asn", None) and not getattr(doc, "is_return", 0):
		refuse_qty_declared_on_open_asns(doc.items)
	breaches = breaches_for_purchase_receipt(doc)
	if not breaches:
		return

	throw_stock_cap_exceeded(breaches)


def _pair_unmapped_rows(doc) -> None:
	"""Map receipt rows the ASN map does not know to free ASN lines on the same PO Item.

	The map is keyed by row name. Amend gives every row a new name (the desk still copies the
	old map), and so does deleting and re-adding a row on a draft. Unpaired, submit records
	nothing and the ASN stays in transit with the stock already on hand. Keys for rows no
	longer on the receipt are dropped.
	"""
	if not getattr(doc, "asn", None) or getattr(doc, "is_return", 0):
		return
	row_names = {row.name for row in doc.items}
	mapping = {
		name: entry
		for name, entry in json.loads(getattr(doc, "asn_items", None) or "{}").items()
		if name in row_names
	}
	unmapped = [row for row in doc.items if row.name not in mapping]
	if not unmapped:
		return

	lines_by_po_item: dict[str, list] = {}
	for asn_item in frappe.get_all(
		"ASN Item",
		filters={"parent": doc.asn, "parenttype": "ASN"},
		fields=["name", "purchase_order_item", "qty", "received_qty"],
		order_by="idx asc",
	):
		lines_by_po_item.setdefault(asn_item.purchase_order_item, []).append(asn_item)

	taken = {entry.get("asn_item_name") for entry in mapping.values()}
	for row in unmapped:
		lines = lines_by_po_item.get(row.purchase_order_item)
		if not lines:
			continue
		# Room left beats everything: the ASN is Received only when every line is full. Among lines
		# with room, prefer one this receipt has not mapped; sharing is fine, since linked
		# recording sums every row mapped to a line.
		# shortcut: a split line the gate skipped can still be picked; read the amended_from map
		# if amended gate-pass receipts start landing on the wrong line.
		asn_item = min(lines, key=lambda line: (flt(line.received_qty) >= flt(line.qty), line.name in taken))
		taken.add(asn_item.name)
		mapping[row.name] = {"asn_item_name": asn_item.name, "original_qty": asn_item.qty}
	doc.asn_items = json.dumps(mapping)


def _gate_pass_mode_on() -> bool:
	if not frappe.db.exists("DocType", "ASN Settings"):
		return False
	return cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode")) == 1


def _set_if_present(doc, fieldname: str, value) -> None:
	if value is None or not doc.meta.has_field(fieldname):
		return
	doc.set(fieldname, value)


def _set_asn_invoice_on_gate_pass(gate_pass, asn) -> None:
	"""Map ASN supplier invoice onto Gate Pass invoice and challan fields when present."""
	_set_if_present(gate_pass, "invoice_number", asn.supplier_invoice_no)
	_set_if_present(gate_pass, "invoice_date", asn.supplier_invoice_date)
	_set_if_present(gate_pass, "challan_number", asn.supplier_invoice_no)
	_set_if_present(gate_pass, "challan_date", asn.supplier_invoice_date)


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
	_set_asn_invoice_on_gate_pass(gate_pass, asn)
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
	_set_asn_invoice_on_gate_pass(gate_pass, asn)
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

	# Material drafts run the site Gate Pass controller. That controller checks
	# material lines on gate_pass_table, so a Job draft that only fills the job
	# line table would be rejected. Skip that validation for Job drafts.
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
	# The field is added at migrate; Gate Pass installed after this app needs another migrate.
	if not frappe.get_meta("Gate Pass").has_field("asn"):
		frappe.throw(_("Gate Pass has no ASN field on this site. Run bench migrate."))

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


GATE_PASS_RECEIPT_ACTION = "create_receipt_from_gate_pass"


@frappe.whitelist(methods=["POST"])
def create_receipt_from_gate_pass(gate_pass_name: str) -> dict:
	"""Open the draft receipt for a submitted Gate Pass.

	A Material Gate In becomes a Purchase Receipt that still carries the ASN.
	A Job Gate In becomes a Subcontracting Receipt linked to the ASN.
	The same roles as the ASN and Subcontracting Order scan actions may call this.
	"""
	frappe.only_for(("Stock User", "Stock Manager"))
	gate_pass = frappe.get_doc("Gate Pass", gate_pass_name)
	if cint(gate_pass.docstatus) != 1:
		frappe.throw(_("Submit the Gate Pass before creating a receipt."))
	if not (getattr(gate_pass, "asn", None) or "").strip():
		frappe.throw(_("Gate Pass {0} is not linked to an ASN").format(gate_pass.name))

	if _is_job_gate_pass(gate_pass):
		return _create_subcontracting_receipt_from_gate_pass(gate_pass)
	return _create_purchase_receipt_from_gate_pass(gate_pass)


def create_receipt_from_gate_pass_scan(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Dispatch adapter: scan the Gate Pass's own code to open its receipt.

	The gate scans the ASN barcode to raise the draft Gate Pass; this action
	is the next link, run from the code stored on the Gate Pass on submit.
	"""
	del source_doctype, payload
	return create_receipt_from_gate_pass(source_name)


def on_gate_pass_submit(doc, method=None):
	"""Store the receipt scan code on a Gate Pass when it is submitted.

	Only a Gate Pass linked to an ASN gets a code: the receipt action refuses
	the others, so their codes would never dispatch. Drafts carry no code; the
	code is stored when the pass is submitted and drawn on the printed pass.
	"""
	del method
	if not (getattr(doc, "asn", None) or "").strip():
		return
	store_scan_code(doc, GATE_PASS_RECEIPT_ACTION)


def on_gate_pass_cancel(doc, method=None):
	"""Void the Gate Pass's scan code so a cancelled pass cannot be scanned."""
	del method
	void_scan_codes(GATE_PASS_RECEIPT_ACTION, "Gate Pass", doc.name)


def _is_job_gate_pass(gate_pass) -> bool:
	if (getattr(gate_pass, "gate_pass_type", None) or "") == "Job":
		return True
	return (getattr(gate_pass, "document_reference", None) or "") == "Subcontracting Order"


def _create_purchase_receipt_from_gate_pass(gate_pass) -> dict:
	existing = _existing_purchase_receipt(gate_pass.asn, gate_pass.name)
	if existing:
		return existing

	from asn_module.handlers.gate_pass_create import map_purchase_receipt_draft_from_gate_pass

	asn = frappe.get_doc("ASN", gate_pass.asn)
	pr = map_purchase_receipt_draft_from_gate_pass(gate_pass)
	_apply_asn_fields(pr, asn, gate_pass=gate_pass)
	fill_custom_fiscal_year(pr)
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
		"message": _("Purchase Receipt {0} created from Gate Pass {1}").format(pr.name, gate_pass.name),
	}


def _create_subcontracting_receipt_from_gate_pass(gate_pass) -> dict:
	asn = frappe.get_doc("ASN", gate_pass.asn)
	result = _open_or_create_subcontracting_receipt(asn)
	receipt = frappe.get_doc("Subcontracting Receipt", result["name"])
	if _apply_gate_pass_qty_to_subcontracting_receipt(receipt, gate_pass):
		receipt.save(ignore_permissions=True)
	return result


def _existing_purchase_receipt(asn_name: str, gate_pass_name: str) -> dict | None:
	"""Open a draft already created for this ASN or Gate Pass.

	A submitted receipt that already names the Gate Pass is refused, so Create
	cannot add a second draft that would receive the same stock again.
	"""
	draft_name = frappe.db.get_value("Purchase Receipt", {"asn": asn_name, "docstatus": 0}, "name")
	if not draft_name and frappe.get_meta("Purchase Receipt").has_field("custom_gate_pass_reference"):
		linked = frappe.db.get_value(
			"Purchase Receipt",
			{"custom_gate_pass_reference": gate_pass_name, "docstatus": ["!=", 2]},
			["name", "docstatus"],
			as_dict=True,
		)
		if linked and cint(linked.docstatus) == 0:
			draft_name = linked.name
		elif linked:
			frappe.throw(
				_("Purchase Receipt {0} already exists for Gate Pass {1}").format(linked.name, gate_pass_name)
			)
	if not draft_name:
		return None
	return {
		"doctype": "Purchase Receipt",
		"name": draft_name,
		"url": f"/app/purchase-receipt/{draft_name}",
		"message": _("Existing draft Purchase Receipt {0} opened").format(draft_name),
	}


def _apply_gate_pass_qty_to_subcontracting_receipt(receipt, gate_pass) -> bool:
	"""Copy arriving qty from the job line table onto the receipt."""
	table_field, _child_fields = _job_line_table(gate_pass)
	qty_by_line = {}
	for row in (gate_pass.get(table_field) if table_field else []) or []:
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
	asn = frappe.get_doc("ASN", asn_name)
	if doc.doctype == "Purchase Receipt":
		# Create on the Gate Pass already mapped the quantity received at the gate.
		# Keep that quantity. The ASN still supplies the link, invoice, batch, and serial.
		_apply_asn_fields(doc, asn, gate_pass=frappe.get_doc("Gate Pass", gate_pass_name))
		return
	doc.meta = frappe.get_meta(doc.doctype)
	if not doc.meta.has_field("asn"):
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
	fill_custom_fiscal_year(receipt)
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


def _apply_asn_fields(pr, asn, *, gate_pass=None) -> None:
	"""Stamp the ASN onto a receipt. With a Gate Pass, keep the qty received at the gate."""
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

	if gate_pass is None:
		_preserve_asn_item_rows(pr, asn.items)
		asn_lines = asn.items
	else:
		# Receipt rows are already one per Gate Pass row; cloning would copy one row's qty.
		asn_lines = _asn_lines_received_at_gate(asn, gate_pass)
	asn_items_by_po_item = {}
	for asn_item in asn_lines:
		asn_items_by_po_item.setdefault(asn_item.purchase_order_item, []).append(asn_item)

	# Row names do not exist until insert, so the map is stamped afterwards, keyed by
	# name: the desk renumbers rows (idx) when a draft is edited, which would silently
	# re-credit quantities to the wrong ASN lines on submit.
	asn_item_pairs = []
	for pr_item in pr.items:
		matching_asn_items = asn_items_by_po_item.get(pr_item.purchase_order_item) or []
		asn_item = matching_asn_items.pop(0) if matching_asn_items else None
		if not asn_item:
			continue

		if gate_pass is None:
			pr_item.qty = flt(asn_item.qty)
			pr_item.stock_qty = flt(asn_item.qty) * flt(pr_item.conversion_factor or 1)
		pr_item.batch_no = asn_item.batch_no
		pr_item.serial_no = asn_item.serial_nos
		_set_amounts_from_qty(pr, pr_item)
		asn_item_pairs.append((pr_item, asn_item))

	pr._asn_item_pairs = asn_item_pairs


def _asn_lines_received_at_gate(asn, gate_pass) -> list:
	"""ASN lines whose Gate Pass row has Receive Qty, in order.

	The Gate Pass is built one row per ASN line in ASN order, so the k-th row on an order
	line is the k-th ASN line on it. A row left at 0 drops its own line, not a sibling's.
	shortcut: pairs by position, so deleting or reordering Gate Pass rows shifts it; upgrade
	to an ASN Item link on the Gate Pass row if the gate starts editing rows.
	"""
	asn_lines_by_po_item = {}
	for asn_item in asn.items:
		asn_lines_by_po_item.setdefault(asn_item.purchase_order_item, []).append(asn_item)
	received = []
	for row in gate_pass.get("items") or []:
		siblings = asn_lines_by_po_item.get(row.purchase_order_item)
		if not siblings:
			continue
		asn_item = siblings.pop(0)
		if gate_pass_receive_qty(row) > 0:
			received.append(asn_item)
	return received


def stamp_asn_item_mapping(doc, method=None) -> None:
	"""Persist the PR-row → ASN-line map keyed by row name (after_insert hook).

	shortcut: drafts created before name keying are not migrated (pre-production)
	"""
	del method
	pairs = getattr(doc, "_asn_item_pairs", None) or []
	if not pairs:
		return
	doc.asn_items = json.dumps(
		{
			pr_item.name: {"asn_item_name": asn_item.name, "original_qty": asn_item.qty}
			for pr_item, asn_item in pairs
		}
	)
	frappe.db.set_value(doc.doctype, doc.name, "asn_items", doc.asn_items, update_modified=False)


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


def on_purchase_receipt_submit(doc, method):
	"""Update ASN receipt tracking and store the follow-up Scan Code on submit.

	Every non-return receipt carries its next step's code, including a
	receipt raised from a Subcontracting Receipt, which has no ASN.

	A return does not record against the ASN. The supplier's shipment already arrived;
	sending some of it back is its own transaction and leaves ``received_qty`` as it is.
	"""
	del method
	if getattr(doc, "is_return", 0):
		return

	_store_invoice_code(doc)

	if not doc.asn:
		return
	mapped_names, _updated = _record_linked_received_qty(doc, sign=1)

	asn = frappe.get_doc("ASN", doc.asn)
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


def _store_invoice_code(doc) -> None:
	"""Store the code that creates this receipt's Purchase Invoice.

	Runs before the ASN bookkeeping so an unlinked receipt (one born from a
	Subcontracting Receipt) is not skipped.
	"""
	store_scan_code(doc, "create_purchase_invoice")
