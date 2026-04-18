from collections.abc import Sequence
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt, today
from frappe.utils.file_manager import save_file
from frappe.website.website_generator import WebsiteGenerator

from asn_module.qr_engine.generate import generate_barcode, generate_qr
from asn_module.supplier_asn_portal import (
	asn_eligible_for_supplier_portal_cancel,
	asn_eligible_for_supplier_portal_delete,
)
from asn_module.traceability import emit_asn_item_transition, get_latest_transition_rows_for_asn


class ASN(WebsiteGenerator):
	def get_context(self, context):
		# WebsiteGenerator (Frappe v16) does not implement get_context on the MRO; only set portal context.
		context.no_cache = 1
		context.show_sidebar = True
		context.doc = self
		context.title = self.name
		context.can_cancel_portal = asn_eligible_for_supplier_portal_cancel(self)
		context.can_delete_portal = asn_eligible_for_supplier_portal_delete(self)

	def validate(self):
		self._validate_items_present()
		self._validate_item_qty()
		self._validate_single_purchase_order()
		self._sync_supplier_invoice_amount_from_items()
		super().validate()
		self._validate_supplier_invoice_unique()
		self._validate_po_qty()

	def on_submit(self):
		asn_date = today()
		qr_code, barcode, scan_label = self._generate_attachments()
		frappe.db.set_value(
			self.doctype,
			self.name,
			{
				"status": "Submitted",
				"asn_date": asn_date,
				"qr_code": qr_code,
				"barcode": barcode,
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
		self._purge_scan_codes_for_asn()
		self._delete_asn_transition_logs()
		self._clear_cancelled_purchase_receipt_asn_links()
		self._validate_deletable_against_purchase_receipts()

	def _purge_scan_codes_for_asn(self):
		"""Remove QR/barcode registry rows so cancel/delete is not blocked by Dynamic Link checks."""
		if not frappe.db.exists("DocType", "Scan Code"):
			return
		frappe.db.delete(
			"Scan Code",
			{"source_doctype": self.doctype, "source_name": self.name},
		)

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
		"""Update ASN status based on received quantities across all items."""
		all_received = True
		any_received = False

		for item in self.items:
			received_qty = flt(item.received_qty)
			qty = flt(item.qty)

			if received_qty > 0:
				any_received = True
			if received_qty < qty:
				all_received = False
			item.discrepancy_qty = qty - received_qty

		status = self.status
		if all_received:
			status = "Received"
		elif any_received:
			status = "Partially Received"

		for item in self.items:
			frappe.db.set_value(
				item.doctype,
				item.name,
				{
					"received_qty": item.received_qty,
					"discrepancy_qty": item.discrepancy_qty,
				},
				update_modified=False,
			)

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

	def _validate_single_purchase_order(self):
		rows = [row for row in self.items or [] if row.purchase_order_item]
		if not rows:
			return

		purchase_order_item_names = [row.purchase_order_item for row in rows]
		po_item_rows = frappe.get_all(
			"Purchase Order Item",
			filters={"name": ["in", purchase_order_item_names]},
			fields=["name", "parent"],
		)
		parent_by_item = {row.name: row.parent for row in po_item_rows}
		missing_items = sorted(set(purchase_order_item_names) - set(parent_by_item))
		if missing_items:
			frappe.throw(
				_("ASN rows reference missing Purchase Order Item values: {0}").format(
					", ".join(missing_items)
				)
			)

		purchase_orders = set()
		mismatched_rows = []
		for row in rows:
			parent_purchase_order = parent_by_item[row.purchase_order_item]
			purchase_orders.add(parent_purchase_order)
			if row.purchase_order and row.purchase_order != parent_purchase_order:
				mismatched_rows.append(
					_("Row {0}: Purchase Order {1} does not match Purchase Order Item parent {2}").format(
						row.idx, row.purchase_order, parent_purchase_order
					)
				)

		if mismatched_rows:
			frappe.throw(_("ASN Purchase Order references are inconsistent:\n{0}").format("\n".join(mismatched_rows)))

		if len(purchase_orders) <= 1:
			return

		frappe.throw(
			_("Each ASN must reference only one purchase order. Found: {0}").format(
				", ".join(sorted(purchase_orders))
			)
		)

	def _sync_supplier_invoice_amount_from_items(self):
		"""When header amount is unset (0), derive it from line qty * rate so the portal/detail view is not stuck at 0."""
		if flt(self.supplier_invoice_amount) != 0:
			return
		total = sum(flt(row.qty) * flt(row.rate) for row in (self.items or []))
		self.supplier_invoice_amount = total

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
		existing_qty_by_item = _get_shipped_qty_by_po_item(
			purchase_order_item_names, exclude_asn_name=self.name or None
		)

		for purchase_order_item, rows in rows_by_purchase_order_item.items():
			po_qty = po_qty_by_item.get(purchase_order_item)
			if not po_qty:
				continue

			current_qty = sum(flt(row.qty) for row in rows)
			already_shipped = existing_qty_by_item.get(purchase_order_item, 0)
			remaining_qty = flt(po_qty) - flt(already_shipped)
			if flt(current_qty) <= flt(remaining_qty):
				continue

			row_numbers = ", ".join(str(row.idx) for row in rows)
			frappe.throw(
				_("Rows {0}: Shipped qty {1} exceeds remaining PO qty {2}").format(
					row_numbers,
					current_qty,
					remaining_qty,
				)
			)

	def _generate_attachments(self) -> tuple[str, str, str]:
		qr_result = generate_qr("create_purchase_receipt", "ASN", self.name)
		barcode_result = generate_barcode("create_purchase_receipt", "ASN", self.name)
		scan_label = qr_result.get("human_readable") or qr_result.get("scan_code", "")

		qr_file = save_file(
			f"{self.name}-qr.png",
			qr_result["image_base64"],
			self.doctype,
			self.name,
			is_private=0,
			decode=True,
		)
		barcode_file = save_file(
			f"{self.name}-barcode.png",
			barcode_result["image_base64"],
			self.doctype,
			self.name,
			is_private=0,
			decode=True,
		)

		return qr_file.file_url, barcode_file.file_url, scan_label


def _get_shipped_qty_by_po_item(
	purchase_order_item_names: Sequence[str], exclude_asn_name: str | None = None
) -> dict[str, float]:
	if not purchase_order_item_names:
		return {}

	asn_item = DocType("ASN Item")
	asn = DocType("ASN")
	query = (
		frappe.qb.from_(asn_item)
		.inner_join(asn)
		.on(asn.name == asn_item.parent)
		.select(asn_item.purchase_order_item, Sum(asn_item.qty).as_("qty"))
		.where(asn_item.purchase_order_item.isin(list(purchase_order_item_names)))
		.where(asn.docstatus != 2)
		.groupby(asn_item.purchase_order_item)
	)
	if exclude_asn_name:
		query = query.where(asn.name != exclude_asn_name)

	rows = query.run(as_dict=True)
	return {row.purchase_order_item: flt(row.qty) for row in rows}


@frappe.whitelist()
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

	shipped_qty_by_item = _get_shipped_qty_by_po_item(
		[poi.purchase_order_item for poi in po_items], exclude_asn_name=asn_name
	)

	result = []
	for poi in po_items:
		already_shipped = shipped_qty_by_item.get(poi.purchase_order_item, 0)
		remaining_qty = flt(poi.qty) - flt(already_shipped)
		if remaining_qty <= 0:
			continue

		result.append(
			{
				"purchase_order": purchase_order,
				"purchase_order_item": poi.purchase_order_item,
				"item_code": poi.item_code,
				"item_name": poi.item_name,
				"qty": remaining_qty,
				"uom": poi.uom,
				"rate": poi.rate,
			}
		)

	return result


@frappe.whitelist()
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


@frappe.whitelist()
def get_item_transition_summary(asn: str) -> list[dict]:
	"""Latest transition row per ASN line item (for compact ASN form summary)."""
	doc = frappe.get_doc("ASN", asn)
	if not doc.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return get_latest_transition_rows_for_asn(asn)


def _get_accessible_purchase_order(purchase_order: str):
	doc = frappe.get_doc("Purchase Order", purchase_order)
	if doc.has_permission("read") or frappe.has_website_permission(doc, "read", user=frappe.session.user):
		return doc

	frappe.throw(
		_("Not permitted to access Purchase Order {0}").format(purchase_order), frappe.PermissionError
	)
