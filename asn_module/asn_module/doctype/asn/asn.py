from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.query_builder.functions import Function, IfNull, Sum
from frappe.utils import cint, flt, today
from frappe.website.website_generator import WebsiteGenerator

from asn_module.handlers.purchase_receipt import asn_dispatch_action_key
from asn_module.qr_engine.scan_codes import resolve_scan_code
from asn_module.stock_cap.api import breaches_for_asn_doc
from asn_module.stock_cap.fetch import cap_branch_by_warehouse, fetch_cap_context
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures, throw_stock_cap_exceeded
from asn_module.stock_cap.models import Breach, Line
from asn_module.stock_cap.precision import flt_qty
from asn_module.supplier_asn_portal import (
	asn_eligible_for_supplier_portal_cancel,
	asn_eligible_for_supplier_portal_delete,
)
from asn_module.traceability import emit_asn_item_transition, get_latest_transition_rows_for_asn
from asn_module.utils.permissions import get_accessible_doc


class ASN(WebsiteGenerator):
	def get_context(self, context):
		# WebsiteGenerator (Frappe v16) does not implement get_context on the MRO; only set portal context.
		context.no_cache = 1
		context.show_sidebar = True
		context.doc = self
		context.title = self.name
		context.can_cancel_portal = asn_eligible_for_supplier_portal_cancel(self)
		context.can_delete_portal = asn_eligible_for_supplier_portal_delete(self)
		context.can_submit_portal = self.docstatus == 0
		context.can_edit_portal = self.docstatus == 0

	def make_route(self):
		"""Keep detail pages under /asn/<name> even with an empty DocType-level route.

		WebsiteGenerator.make_route() only prefixes meta.route. That field stays empty so
		/asn resolves to the supplier portal list; without this override each ASN would
		publish at a bare /asn-0001 path instead of /asn/asn-0001.
		"""
		return f"asn/{self.scrubbed_title()}"

	def validate(self):
		self._validate_vehicle_number_present()
		self._validate_one_order()
		self._validate_order_lines()
		if cint(self.docstatus) == 1:
			self._validate_items_present()
			self._validate_item_qty()
			self._validate_supplier_invoice_no_present()
		super().validate()
		self._validate_supplier_invoice_unique()
		self._validate_po_qty()
		self._validate_subcontracting_lines()
		self._warn_stock_cap()

	def before_submit(self):
		self._validate_stock_cap()

	def on_submit(self):
		asn_date = today()
		scan_label = resolve_scan_code(asn_dispatch_action_key(), "ASN", self.name)
		frappe.db.set_value(
			self.doctype,
			self.name,
			{
				"status": "Submitted",
				"asn_date": asn_date,
				"scan_code_label": scan_label,
			},
			update_modified=False,
		)
		self.reload()

		for row in self.items:
			emit_asn_item_transition(
				asn=self.name,
				asn_item=row.name,
				item_code=row.item_code,
				state="ASN_GENERATED",
				transition_status="OK",
				ref_doctype=self.doctype,
				ref_name=self.name,
			)

	def before_cancel(self):
		self._purge_scan_codes_for_asn()
		self._delete_linked_draft_purchase_receipts()

	def on_cancel(self):
		frappe.db.set_value(self.doctype, self.name, "status", "Cancelled", update_modified=False)
		self.reload()

	def on_trash(self):
		# Scan Code / Scan Log cleanup runs via the global on_trash hook on purge_scan_registry_on_trash.
		self._delete_asn_transition_logs()
		self._clear_cancelled_purchase_receipt_asn_links()
		self._validate_deletable_against_purchase_receipts()

	def _purge_scan_codes_for_asn(self):
		"""Remove QR/barcode registry rows so cancel/delete is not blocked by Dynamic Link checks."""
		from asn_module.qr_engine.scan_codes import purge_scan_codes_for_source

		purge_scan_codes_for_source(self.doctype, self.name)

	def _delete_asn_transition_logs(self):
		"""Remove traceability rows so ASN delete is not blocked by Link checks (logs are ASN-specific)."""
		if not frappe.db.exists("DocType", "ASN Transition Log"):
			return
		frappe.db.delete("ASN Transition Log", {"asn": self.name})

	def _clear_cancelled_purchase_receipt_asn_links(self):
		"""Drop ASN link on cancelled receipts so deletion is not blocked by a stale Link field."""
		if not frappe.db.has_column("Purchase Receipt", "asn"):
			return
		frappe.db.sql(
			"UPDATE `tabPurchase Receipt` SET `asn` = NULL WHERE `asn` = %s AND `docstatus` = 2",
			(self.name,),
		)

	def _delete_linked_draft_purchase_receipts(self):
		"""Remove draft PRs created from this ASN so the notice can be deleted after cancel without a manual PR delete."""
		if not frappe.db.has_column("Purchase Receipt", "asn"):
			return
		for pr_name in frappe.get_all(
			"Purchase Receipt",
			filters={"asn": self.name, "docstatus": 0},
			pluck="name",
		):
			frappe.delete_doc("Purchase Receipt", pr_name)

	def update_receipt_status(self):
		"""Set discrepancy and status from the received quantities stored in the database.

		Receipt handlers add to ``received_qty`` in SQL, so it is read from the table and
		never written back from this (possibly stale) document.
		"""
		asn_item = DocType("ASN Item")
		(
			frappe.qb.update(asn_item)
			.set(asn_item.discrepancy_qty, asn_item.qty - IfNull(asn_item.received_qty, 0))
			.where(asn_item.parent == self.name)
		).run()
		# Locking read: a plain read under REPEATABLE READ can miss a concurrent receipt.
		rows = (
			frappe.qb.from_(asn_item)
			.select(asn_item.qty, asn_item.received_qty)
			.where(asn_item.parent == self.name)
			.for_update()
		).run(as_dict=True)

		received = [flt_qty(row.received_qty) for row in rows]
		all_received = bool(rows) and all(
			received_qty >= flt_qty(row.qty) for received_qty, row in zip(received, rows, strict=True)
		)
		any_received = any(received_qty > 0 for received_qty in received)

		status = self.status
		if all_received:
			status = "Received"
		elif any_received:
			status = "Partially Received"
		elif status in ("Received", "Partially Received"):
			status = "Submitted"

		if status != self.status:
			frappe.db.set_value(self.doctype, self.name, "status", status, update_modified=False)

		self.reload()

	def _validate_items_present(self):
		if self.items:
			return

		frappe.throw(_("At least one item is required in the ASN"))

	def _validate_item_qty(self):
		for row in self.items or []:
			if flt(row.qty) > 0:
				continue

			frappe.throw(_("Row {0}: Quantity must be greater than 0").format(row.idx))

	def _validate_vehicle_number_present(self):
		if (self.vehicle_number or "").strip():
			return
		frappe.throw(_("Vehicle Number is required."))

	def _validate_supplier_invoice_no_present(self):
		if (self.supplier_invoice_no or "").strip():
			return
		frappe.throw(_("Supplier Invoice No is required."))

	def _validate_supplier_invoice_unique(self):
		if not self.supplier_invoice_no:
			return

		filters: dict[str, Any] = {
			"supplier": self.supplier,
			"supplier_invoice_no": self.supplier_invoice_no,
			"docstatus": ("!=", 2),
		}
		if self.name:
			filters["name"] = ("!=", self.name)

		existing = frappe.db.exists("ASN", filters)
		if existing:
			frappe.throw(
				_("Supplier Invoice No {0} already exists for Supplier {1}").format(
					self.supplier_invoice_no, self.supplier
				)
			)

	def _validate_deletable_against_purchase_receipts(self):
		"""Block ASN deletion while a draft or submitted Purchase Receipt still references this ASN.

		Cancelled receipts are unlinked in on_trash before this runs.
		"""
		if not frappe.db.has_column("Purchase Receipt", "asn"):
			return
		linked = frappe.db.get_value("Purchase Receipt", {"asn": self.name}, "name")
		if not linked:
			return
		frappe.throw(
			_(
				"Cannot delete ASN {0} while Purchase Receipt {1} is linked. "
				"Remove draft receipts or cancel and delete receipts that reference this ASN."
			).format(self.name, linked),
			frappe.LinkExistsError,
		)

	def _validate_one_order(self):
		"""A line is one Purchase Order line or one Subcontracting Order line.

		Every line on the notice names that same order. Purchase Order quantity
		checks stay in ``_validate_po_qty`` and only see Purchase Order lines.
		"""
		orders: set[tuple[str, str]] = set()
		for row in self.items or []:
			purchase_order = (row.purchase_order or "").strip()
			purchase_order_item = (row.purchase_order_item or "").strip()
			subcontracting_order = (row.subcontracting_order or "").strip()
			subcontracting_order_item = (row.subcontracting_order_item or "").strip()
			has_purchase_order = bool(purchase_order or purchase_order_item)
			has_subcontracting_order = bool(subcontracting_order or subcontracting_order_item)
			if has_purchase_order and has_subcontracting_order:
				frappe.throw(_("An ASN can reference only one order."))
			if has_purchase_order:
				if not purchase_order or not purchase_order_item:
					frappe.throw(
						_("Row {0}: a Purchase Order line needs the order and the order line.").format(
							row.idx
						)
					)
				orders.add(("Purchase Order", purchase_order))
				continue
			if has_subcontracting_order:
				if not subcontracting_order or not subcontracting_order_item:
					frappe.throw(
						_("Row {0}: a Subcontracting Order line needs the order and the order line.").format(
							row.idx
						)
					)
				orders.add(("Subcontracting Order", subcontracting_order))
				continue
			frappe.throw(
				_("Row {0}: reference one Purchase Order or one Subcontracting Order.").format(row.idx)
			)

		if len(orders) > 1:
			frappe.throw(_("An ASN can reference only one order."))

	def _validate_order_lines(self):
		"""Each row names a real line of an open order that belongs to this supplier.

		One query per order type reads every referenced line with its order. The
		client-side supplier filter is not a check, and the order line decides the
		item and UOM. A draft order is still allowed; a cancelled one is not.
		"""
		for order_doctype in ("Purchase Order", "Subcontracting Order"):
			order_field = frappe.scrub(order_doctype)
			rows = [row for row in self.items or [] if row.get(f"{order_field}_item")]
			if not rows:
				continue

			line_doctype = DocType(f"{order_doctype} Item")
			order = DocType(order_doctype)
			uom_field = "uom" if order_doctype == "Purchase Order" else "stock_uom"
			lines = {
				line.name: line
				for line in (
					frappe.qb.from_(line_doctype)
					.inner_join(order)
					.on(order.name == line_doctype.parent)
					.select(
						line_doctype.name,
						line_doctype.parent,
						line_doctype.item_code,
						getattr(line_doctype, uom_field).as_("uom"),
						order.supplier,
						order.docstatus,
					)
					.where(line_doctype.name.isin([row.get(f"{order_field}_item") for row in rows]))
				).run(as_dict=True)
			}

			for row in rows:
				line_name = row.get(f"{order_field}_item")
				order_name = row.get(order_field)
				line = lines.get(line_name)
				if not line:
					frappe.throw(
						_("Row {0}: {1} line {2} does not exist").format(row.idx, _(order_doctype), line_name)
					)
				if line.parent != order_name:
					frappe.throw(
						_("Row {0}: {1} line {2} belongs to {3}, not {4}").format(
							row.idx, _(order_doctype), line_name, line.parent, order_name
						)
					)
				if cint(line.docstatus) == 2:
					frappe.throw(
						_("Row {0}: {1} {2} is cancelled").format(row.idx, _(order_doctype), order_name)
					)
				if line.supplier != self.supplier:
					frappe.throw(
						_("Row {0}: Supplier {1} does not match {2} {3}, which is for {4}").format(
							row.idx, self.supplier, _(order_doctype), order_name, line.supplier
						)
					)
				if row.item_code != line.item_code:
					frappe.throw(
						_("Row {0}: Item Code {1} does not match {2} on {3} line {4}").format(
							row.idx, row.item_code, line.item_code, _(order_doctype), line_name
						)
					)
				if row.uom and row.uom != line.uom:
					frappe.throw(
						_("Row {0}: UOM {1} does not match {2} on {3} line {4}").format(
							row.idx, row.uom, line.uom, _(order_doctype), line_name
						)
					)

	def _validate_po_qty(self):
		rows_by_purchase_order_item = {}
		for row in self.items or []:
			if not row.purchase_order or not row.purchase_order_item:
				continue

			rows_by_purchase_order_item.setdefault(row.purchase_order_item, []).append(row)

		if not rows_by_purchase_order_item:
			return

		purchase_order_item_names = list(rows_by_purchase_order_item)
		po_items = frappe.get_all(
			"Purchase Order Item",
			filters={"name": ["in", purchase_order_item_names]},
			fields=["name", "qty"],
		)
		po_qty_by_item = {row.name: flt(row.qty) for row in po_items}
		for name in purchase_order_item_names:
			po_qty_by_item.setdefault(name, 0)
		qty_state = _purchase_order_item_qty_state(po_qty_by_item, exclude_asn_name=self.name or None)

		for purchase_order_item, rows in rows_by_purchase_order_item.items():
			po_qty = po_qty_by_item[purchase_order_item]
			current_qty = sum(flt(row.qty) for row in rows)
			# Net received already includes receipts against this ASN. Add back only the
			# received quantity that this Shipped Qty still covers, so a partly received
			# shipment can be saved again and an over-received line is not counted twice.
			received_within_shipped = sum(min(flt(row.qty), max(flt(row.received_qty), 0)) for row in rows)
			po_line_qty = qty_state[purchase_order_item]
			past_remaining, remaining_qty = po_line_qty.shipped_qty_past_remaining(
				ordered_qty=po_qty,
				shipped_qty=current_qty,
				received_within_shipped=received_within_shipped,
			)
			if not past_remaining:
				continue

			row_numbers = ", ".join(str(row.idx) for row in rows)
			frappe.throw(
				_("Rows {0}: Shipped qty {1} exceeds remaining PO qty {2}").format(
					row_numbers,
					current_qty,
					remaining_qty,
				)
			)

	def _validate_subcontracting_lines(self):
		"""One row per Subcontracting Order line, and Shipped Qty within what is still open.

		A receipt maps each order line once. Two notice rows for the same line would
		keep only the first quantity. Remaining qty is the order line's qty minus
		what that line has already received.
		"""
		rows_by_line: dict[str, list] = {}
		for row in self.items or []:
			line_name = (row.subcontracting_order_item or "").strip()
			if not line_name:
				continue
			rows_by_line.setdefault(line_name, []).append(row)

		for line_name, rows in rows_by_line.items():
			if len(rows) < 2:
				continue
			row_numbers = ", ".join(str(row.idx) for row in rows)
			frappe.throw(
				_("Rows {0}: duplicate Subcontracting Order line {1} is not allowed.").format(
					row_numbers,
					line_name,
				)
			)

		if not rows_by_line:
			return

		order_lines = frappe.get_all(
			"Subcontracting Order Item",
			filters={"name": ["in", list(rows_by_line)]},
			fields=["name", "qty", "received_qty"],
		)
		remaining_by_line = {row.name: flt_qty(flt(row.qty) - flt(row.received_qty)) for row in order_lines}
		for line_name, rows in rows_by_line.items():
			shipped_qty = flt_qty(sum(flt(row.qty) for row in rows))
			remaining_qty = remaining_by_line.get(line_name, 0)
			if shipped_qty <= remaining_qty:
				continue
			row_numbers = ", ".join(str(row.idx) for row in rows)
			frappe.throw(
				_("Rows {0}: Shipped qty {1} exceeds remaining Subcontracting Order qty {2}").format(
					row_numbers,
					shipped_qty,
					remaining_qty,
				)
			)

	def _warn_stock_cap(self):
		"""Surface cap breaches on save without blocking. Drafts must always be saveable.

		Submit runs validate and then before_submit. The block is the submit message;
		the orange warning would only repeat it.
		"""
		if getattr(self, "_action", None) == "submit":
			return

		breaches = breaches_for_asn_doc(self)
		if not breaches:
			return

		frappe.msgprint(
			format_breaches(breaches, detailed=may_see_stock_figures()),
			title=_("Stock Cap Warning"),
			indicator="orange",
		)

	def _validate_stock_cap(self):
		"""Block submission. Runs in before_submit so nothing is written before the block."""
		breaches = breaches_for_asn_doc(self)
		if not breaches:
			return

		throw_stock_cap_exceeded(breaches)


_PO_STATUSES_WITH_NO_SHIPPED_QTY = ("Closed", "On Hold")


def _unreceived_qty_by_po_item(
	purchase_order_item_names: Sequence[str], exclude_asn_name: str | None = None
) -> dict[str, float]:
	"""Shipped Qty not yet received, on ASNs that are not Cancelled or Closed.

	A line whose Received Qty already covers its Shipped Qty adds nothing. The ASN named
	in ``exclude_asn_name`` is left out. Receipts against that ASN stay in the Purchase
	Order's net received quantity; the save check adds them back for that document only.
	"""
	if not purchase_order_item_names:
		return {}

	asn_item = DocType("ASN Item")
	asn = DocType("ASN")
	unreceived = Function("GREATEST", asn_item.qty - Function("IFNULL", asn_item.received_qty, 0), 0)
	query = (
		frappe.qb.from_(asn_item)
		.inner_join(asn)
		.on(asn.name == asn_item.parent)
		.select(asn_item.purchase_order_item, Sum(unreceived).as_("qty"))
		.where(asn_item.purchase_order_item.isin(list(purchase_order_item_names)))
		.where(asn.docstatus != 2)
		.where(asn.status != "Closed")
		.groupby(asn_item.purchase_order_item)
	)
	if exclude_asn_name:
		query = query.where(asn.name != exclude_asn_name)

	rows = query.run(as_dict=True)
	return {row.purchase_order_item: flt(row.qty) for row in rows}


@dataclass(frozen=True)
class _PurchaseOrderLine:
	"""What a Purchase Order line contributes to Remaining Qty.

	``net_received`` is ERPNext's figure, already net of returns and of a stock-updating
	Purchase Invoice, in the line's purchase UOM. ``accepts_no_shipped_qty`` is a Closed
	or On Hold order. ``item_code`` is how the over-receipt allowance is found.
	"""

	net_received: float
	item_code: str | None
	accepts_no_shipped_qty: bool
	unit_price: bool = False
	branch: str = ""
	warehouse: str = ""
	conversion_factor: float = 1.0


def _purchase_order_lines(purchase_order_item_names: Sequence[str]) -> dict[str, _PurchaseOrderLine]:
	if not purchase_order_item_names:
		return {}

	po_item = DocType("Purchase Order Item")
	po = DocType("Purchase Order")
	has_unit_price = frappe.db.has_column("Purchase Order", "has_unit_price_items")
	has_branch = frappe.db.has_column("Purchase Order", "branch")
	selected = [
		po_item.name,
		po_item.received_qty,
		po_item.item_code,
		po_item.qty,
		po_item.warehouse,
		po_item.conversion_factor,
		po.status,
		po.set_warehouse,
	]
	if has_unit_price:
		selected.append(po.has_unit_price_items)
	if has_branch:
		selected.append(po.branch)
	rows = (
		frappe.qb.from_(po_item)
		.inner_join(po)
		.on(po.name == po_item.parent)
		.select(*selected)
		.where(po_item.name.isin(list(purchase_order_item_names)))
		.run(as_dict=True)
	)
	lines = {}
	for row in rows:
		factor = flt(row.conversion_factor)
		lines[row.name] = _PurchaseOrderLine(
			net_received=flt(row.received_qty),
			item_code=row.item_code,
			accepts_no_shipped_qty=row.status in _PO_STATUSES_WITH_NO_SHIPPED_QTY,
			unit_price=bool(has_unit_price and cint(row.has_unit_price_items) and not flt(row.qty)),
			branch=(row.branch or "") if has_branch else "",
			warehouse=row.warehouse or row.set_warehouse or "",
			conversion_factor=factor if factor > 0 else 1.0,
		)
	return lines


def _over_receipt_allowance_percent(
	item_code: str | None, stock_allowance: float | None
) -> tuple[float, float | None]:
	"""The percent a Purchase Receipt would allow everyone on this Item.

	ERPNext uses the Item's over-receipt allowance when it is set. A zero on the Item is
	unset and falls through to Stock Settings. The role allowed to over-receive is not
	consulted: an ASN stops at this percent for every user.
	"""
	item_allowance = 0
	if item_code:
		item_allowance = frappe.get_cached_value("Item", item_code, "over_delivery_receipt_allowance")
	if item_allowance:
		return flt(item_allowance), stock_allowance
	if stock_allowance is None:
		stock_allowance = flt(frappe.get_single_value("Stock Settings", "over_delivery_receipt_allowance"))
	return flt(stock_allowance), stock_allowance


def _ordered_qty_with_allowance(ordered_qty: float, allowance_percent: float) -> float:
	"""Ordered quantity expanded the way ERPNext expands a receipt ceiling."""
	return flt(flt(ordered_qty) * (100 + flt(allowance_percent)) / 100)


# ERPNext refuses a receipt when overflow percent minus the allowance is above this.
_OVER_RECEIPT_TOLERANCE_PERCENT = 0.01


def _exceeds_over_receipt_allowance(
	would_be_qty: float, ordered_qty: float, allowance_percent: float
) -> bool:
	"""ERPNext's overflow test, stopping at the allowance for every user."""
	if not ordered_qty:
		return would_be_qty > 0
	overflow_percent = ((would_be_qty - ordered_qty) / ordered_qty) * 100
	return overflow_percent - allowance_percent > _OVER_RECEIPT_TOLERANCE_PERCENT


@dataclass(frozen=True)
class _PurchaseOrderItemQty:
	"""Remaining Qty for one Purchase Order Item, and the figures save compares to it.

	Displayed Remaining Qty stops at the allowance ceiling, or at zero when the order
	accepts no new Shipped Qty. Save still needs net received, unreceived Shipped Qty,
	and the allowance, because ERPNext's overflow test allows 0.01 percent past that ceiling.
	"""

	remaining: float | None
	allowance: float
	accepts_no_shipped_qty: bool
	net_received: float
	unreceived: float
	unit_price: bool = False

	def shipped_qty_past_remaining(
		self, *, ordered_qty: float, shipped_qty: float, received_within_shipped: float
	) -> tuple[bool, float]:
		"""Whether this Shipped Qty is past Remaining Qty, and the Remaining Qty to state.

		Receipts against this ASN are already inside net received. ``received_within_shipped``
		adds back only what this Shipped Qty still covers, so a partly received shipment is
		not refused for goods already receipted. A Closed or On Hold order stops there.
		An open order uses the overflow test and does not consult the over-receive role.
		A unit-price line has no ordered quantity. Its ceiling is the branch stock cap,
		enforced on submit, so save does not treat the zero order as fully shipped.
		"""
		if self.unit_price and not self.accepts_no_shipped_qty:
			return False, 0.0
		remaining_qty = flt(self.remaining) + received_within_shipped
		if self.accepts_no_shipped_qty:
			return flt(shipped_qty) > remaining_qty, remaining_qty
		would_be_qty = (
			flt(self.net_received) - received_within_shipped + flt(self.unreceived) + flt(shipped_qty)
		)
		past = _exceeds_over_receipt_allowance(would_be_qty, ordered_qty, flt(self.allowance))
		return past, remaining_qty


def _purchase_order_item_qty_state(
	ordered_qty_by_name: dict[str, float], *, exclude_asn_name: str | None = None
) -> dict[str, _PurchaseOrderItemQty]:
	if not ordered_qty_by_name:
		return {}

	names = list(ordered_qty_by_name)
	lines = _purchase_order_lines(names)
	shipped_qty_by_item = _unreceived_qty_by_po_item(names, exclude_asn_name=exclude_asn_name)
	unit_price_lines = {
		name: line for name, line in lines.items() if line.unit_price and not line.accepts_no_shipped_qty
	}
	unit_price_remaining = _unit_price_remaining_purchase_qty(
		unit_price_lines, exclude_asn_name=exclude_asn_name
	)
	state: dict[str, _PurchaseOrderItemQty] = {}
	stock_allowance: float | None = None
	for name, ordered_qty in ordered_qty_by_name.items():
		line = lines.get(name) or _PurchaseOrderLine(
			net_received=0, item_code=None, accepts_no_shipped_qty=False
		)
		allowance, stock_allowance = _over_receipt_allowance_percent(line.item_code, stock_allowance)
		unreceived = flt(shipped_qty_by_item.get(name, 0))
		if line.accepts_no_shipped_qty:
			remaining = 0
		elif line.unit_price:
			remaining = unit_price_remaining.get(name)
		else:
			qty = _ordered_qty_with_allowance(ordered_qty, allowance) - line.net_received - unreceived
			remaining = qty if qty > 0 else 0
		state[name] = _PurchaseOrderItemQty(
			remaining=remaining,
			allowance=allowance,
			accepts_no_shipped_qty=line.accepts_no_shipped_qty,
			net_received=line.net_received,
			unreceived=unreceived,
			unit_price=line.unit_price,
		)
	return state


def _unit_price_remaining_purchase_qty(
	lines: dict[str, _PurchaseOrderLine], *, exclude_asn_name: str | None
) -> dict[str, float | None]:
	"""Purchase quantity still allowed on a unit-price line.

	``None`` means no branch cap applies, so the supplier may declare any positive
	quantity. A number is the cap headroom in the purchase UOM, using the same branch,
	warehouse, and precision as submit. Zero means the branch cannot take any more.
	"""
	if not lines:
		return {}

	owners = cap_branch_by_warehouse([line.warehouse for line in lines.values()])
	probes: list[Line] = []
	branch_by_name: dict[str, str] = {}
	for name, line in lines.items():
		if not line.warehouse or not line.item_code:
			continue
		branch = owners.get(line.warehouse) or line.branch or ""
		branch_by_name[name] = branch
		probes.append(
			Line(
				branch=branch,
				item_code=line.item_code,
				warehouse=line.warehouse,
				stock_qty=1,
				row_idx=0,
				conversion_factor=line.conversion_factor,
			)
		)

	context = fetch_cap_context(probes, exclude_asn_name=exclude_asn_name) if probes else None
	remaining: dict[str, float | None] = {}
	for name, line in lines.items():
		branch = branch_by_name.get(name) or ""
		cap_warehouses = context.cap_warehouses.get(branch) if context and branch else None
		cap = float(context.max_stock.get((branch, line.item_code or ""), 0) or 0) if context else 0
		if not cap_warehouses or line.warehouse not in cap_warehouses or cap <= 0 or not line.item_code:
			remaining[name] = None
			continue
		on_hand = float(context.on_hand.get((branch, line.item_code), 0) or 0)
		in_transit = float(context.in_transit.get((branch, line.item_code), 0) or 0)
		baseline = on_hand + in_transit
		remaining[name] = Breach(
			branch=branch,
			item_code=line.item_code,
			row_idxs=(),
			on_hand=on_hand,
			in_transit=in_transit,
			baseline=baseline,
			incoming=0,
			projected=baseline,
			cap=cap,
			conversion_factor=line.conversion_factor,
		).allowed_purchase_qty
	return remaining


def remaining_qty_by_purchase_order_item(
	ordered_qty_by_name: dict[str, float], *, exclude_asn_name: str | None = None
) -> dict[str, float | None]:
	"""Remaining Qty for each Purchase Order Item, in the line's purchase UOM.

	The ordered quantity expanded by the over-receipt allowance, minus the Purchase Order
	Item's net received quantity, minus Shipped Qty declared but not yet received on ASNs
	that are not Closed or Cancelled. Never below zero. The ASN named in
	``exclude_asn_name`` is left out of the unreceived sum. The save check then adds
	back the received quantity already on that ASN, so its own receipts are not counted twice.

	A unit-price line (ordered quantity zero on a Purchase Order flagged
	``has_unit_price_items``) has no ordered ceiling. Its remaining quantity is the
	branch stock-cap headroom, or ``None`` when no cap applies.
	"""
	return {
		name: row.remaining
		for name, row in _purchase_order_item_qty_state(
			ordered_qty_by_name, exclude_asn_name=exclude_asn_name
		).items()
	}


@frappe.whitelist(methods=["GET"])
def get_purchase_order_items(purchase_order: str, asn_name: str | None = None) -> list[dict]:
	_get_accessible_purchase_order(purchase_order)
	po_items = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=[
			"name as purchase_order_item",
			"item_code",
			"item_name",
			"qty",
			"uom",
			"rate",
		],
	)

	ordered_qty_by_name = {poi.purchase_order_item: flt(poi.qty) for poi in po_items}
	remaining_by_item = remaining_qty_by_purchase_order_item(ordered_qty_by_name, exclude_asn_name=asn_name)

	result = []
	for poi in po_items:
		remaining_qty = remaining_by_item.get(poi.purchase_order_item, 0)
		if remaining_qty is None:
			offered_qty = 1
		elif remaining_qty <= 0:
			continue
		else:
			offered_qty = remaining_qty

		result.append(
			{
				"purchase_order": purchase_order,
				"purchase_order_item": poi.purchase_order_item,
				"item_code": poi.item_code,
				"item_name": poi.item_name,
				"qty": offered_qty,
				"uom": poi.uom,
				"rate": poi.rate,
			}
		)

	return result


@frappe.whitelist(methods=["GET"])
def get_po_items(
	doctype: str,
	txt: str,
	searchfield: str,
	start: int,
	page_len: int,
	filters: dict[str, Any] | None,
) -> list[tuple[str, str]]:
	del doctype, searchfield
	purchase_order = (filters or {}).get("purchase_order")
	if not purchase_order:
		return []
	_get_accessible_purchase_order(purchase_order)

	return frappe.db.sql(
		"""
		SELECT poi.item_code, poi.item_name
		FROM `tabPurchase Order Item` poi
		WHERE poi.parent = %s
		AND (poi.item_code LIKE %s OR poi.item_name LIKE %s)
		LIMIT %s OFFSET %s
		""",
		(purchase_order, f"%{txt}%", f"%{txt}%", page_len, start),
	)


@frappe.whitelist(methods=["GET"])
def get_item_transition_summary(asn: str) -> list[dict]:
	"""Latest transition row per ASN line item (for compact ASN form summary)."""
	doc = frappe.get_doc("ASN", asn)
	if not doc.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return get_latest_transition_rows_for_asn(asn)


def _get_accessible_purchase_order(purchase_order: str):
	return get_accessible_doc("Purchase Order", purchase_order)
