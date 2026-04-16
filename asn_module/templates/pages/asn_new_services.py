from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

from asn_module.asn_module.doctype.asn.asn import _get_shipped_qty_by_po_item
from asn_module.templates.pages.asn import get_open_purchase_orders_for_supplier

OPEN_PO_STATUSES = ("To Receive", "To Receive and Bill")
MAX_BULK_ROWS = 5000
MAX_BULK_INVOICES = 500
INVOICE_GROUP_FIELDS = (
	"supplier_invoice_date",
	"expected_delivery_date",
	"lr_no",
	"lr_date",
	"transporter_name",
	"vehicle_number",
	"driver_contact",
	"supplier_invoice_amount",
)


@dataclass
class PortalValidationError(Exception):
	errors: list[dict]

	def __str__(self):
		return "\n".join(error.get("message", "") for error in self.errors)


@dataclass(frozen=True)
class ParsedSingleRow:
	row_number: int
	purchase_order: str
	sr_no: str
	item_code: str
	uom: str
	qty: float
	rate: float


@dataclass(frozen=True)
class ParsedBulkRow:
	row_number: int
	supplier_invoice_no: str
	supplier_invoice_date: str
	expected_delivery_date: str
	lr_no: str
	lr_date: str
	transporter_name: str
	vehicle_number: str
	driver_contact: str
	supplier_invoice_amount: float
	purchase_order: str
	sr_no: str
	item_code: str
	qty: float
	rate: float | None


def error_entry(
	*,
	message: str,
	row_number: int | None = None,
	field: str | None = None,
	invoice_no: str | None = None,
) -> dict:
	return {
		"row_number": row_number,
		"invoice_no": invoice_no,
		"field": field,
		"message": message,
	}


def get_supplier_open_purchase_orders(supplier: str) -> dict[str, frappe._dict]:
	open_purchase_orders = get_open_purchase_orders_for_supplier(supplier)
	return {row.name: row for row in open_purchase_orders}


def validate_supplier_invoices_not_reused(supplier: str, invoice_numbers: list[str]):
	"""Raise PortalValidationError if any invoice number is already on a non-cancelled ASN."""
	errors: list[dict] = []
	for raw in invoice_numbers:
		inv = (raw or "").strip()
		if not inv:
			continue
		filters = {
			"supplier": supplier,
			"supplier_invoice_no": inv,
			"docstatus": ("!=", 2),
		}
		if not frappe.db.exists("ASN", filters):
			continue
		errors.append(
			error_entry(
				invoice_no=inv,
				field="supplier_invoice_no",
				message=_(
					"Supplier invoice number {0} is already used on another notice. "
					"Use a different number, or cancel that notice from your ASN list if it is still submitted "
					"and no purchase receipt has been created yet."
				).format(inv),
			)
		)
	if errors:
		raise PortalValidationError(errors)


def validate_selected_purchase_orders(
	*,
	supplier: str,
	selected_purchase_orders: list[str],
	field: str = "purchase_order",
):
	if not selected_purchase_orders:
		raise PortalValidationError(
			[
				error_entry(
					field=field,
					message=_("Select at least one open Purchase Order."),
				)
			]
		)

	open_po_map = get_supplier_open_purchase_orders(supplier)
	invalid = sorted(po for po in selected_purchase_orders if po not in open_po_map)
	if invalid:
		raise PortalValidationError(
			[
				error_entry(
					field=field,
					message=_("Only open Purchase Orders can be selected. Invalid selections: {0}").format(
						", ".join(invalid)
					),
				)
			]
		)

	return open_po_map


def parse_positive_qty(value: str, *, row_number: int, field: str, invoice_no: str | None = None) -> float:
	qty = flt(value)
	if qty > 0:
		return qty
	raise PortalValidationError(
		[
			error_entry(
				row_number=row_number,
				field=field,
				invoice_no=invoice_no,
				message=_("Row {0}: qty must be greater than 0.").format(row_number),
			)
		]
	)


def parse_non_negative_rate(
	value: str, *, row_number: int, field: str, invoice_no: str | None = None
) -> float:
	rate = flt(value)
	if rate >= 0:
		return rate
	raise PortalValidationError(
		[
			error_entry(
				row_number=row_number,
				field=field,
				invoice_no=invoice_no,
				message=_("Row {0}: {1} cannot be negative.").format(row_number, field),
			)
		]
	)


def parse_optional_non_negative_rate(
	value: str | None, *, row_number: int, field: str, invoice_no: str | None = None
) -> float | None:
	if not (value or "").strip():
		return None
	return parse_non_negative_rate(
		(value or "").strip(), row_number=row_number, field=field, invoice_no=invoice_no
	)


def parse_required_supplier_invoice_amount(
	value: str | None, *, row_number: int, invoice_no: str | None = None
) -> float:
	raw = (value or "").strip()
	if not raw:
		raise PortalValidationError(
			[
				error_entry(
					row_number=row_number,
					field="supplier_invoice_amount",
					invoice_no=invoice_no,
					message=_("Row {0}: supplier_invoice_amount is required.").format(row_number),
				)
			]
		)
	return parse_non_negative_rate(
		raw, row_number=row_number, field="supplier_invoice_amount", invoice_no=invoice_no
	)


def fetch_purchase_order_items(
	purchase_orders: list[str],
) -> tuple[dict[tuple[str, str], list[frappe._dict]], dict[str, float]]:
	if not purchase_orders:
		return {}, {}

	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": ["in", purchase_orders]},
		fields=["name", "parent", "idx", "item_code", "uom", "rate", "qty"],
		limit_page_length=0,
	)
	po_item_qty_by_name = {row.name: flt(row.qty) for row in rows}
	shipped_qty_by_item = _get_shipped_qty_by_po_item([row.name for row in rows])
	remaining_qty_by_name = {
		name: flt(po_item_qty_by_name.get(name, 0)) - flt(shipped_qty_by_item.get(name, 0))
		for name in po_item_qty_by_name
	}

	rows_by_key: dict[tuple[str, str], list[frappe._dict]] = {}
	for row in rows:
		sr_no = str(row.idx).strip()
		rows_by_key.setdefault((row.parent, sr_no), []).append(row)

	return rows_by_key, remaining_qty_by_name


def resolve_po_item(
	*,
	purchase_order: str,
	sr_no: str,
	item_code: str,
	row_number: int,
	invoice_no: str | None,
	rows_by_key: dict[tuple[str, str], list[frappe._dict]],
) -> frappe._dict:
	candidates = rows_by_key.get((purchase_order, sr_no), [])
	if not candidates:
		raise PortalValidationError(
			[
				error_entry(
					row_number=row_number,
					field="sr_no",
					invoice_no=invoice_no,
					message=_("Row {0}: No PO item found for PO {1} and sr_no {2}.").format(
						row_number, purchase_order, sr_no
					),
				)
			]
		)
	if len(candidates) > 1:
		raise PortalValidationError(
			[
				error_entry(
					row_number=row_number,
					field="sr_no",
					invoice_no=invoice_no,
					message=_("Row {0}: Ambiguous PO item mapping for PO {1} and sr_no {2}.").format(
						row_number, purchase_order, sr_no
					),
				)
			]
		)

	row = candidates[0]
	if (row.item_code or "").strip() != item_code.strip():
		raise PortalValidationError(
			[
				error_entry(
					row_number=row_number,
					field="item_code",
					invoice_no=invoice_no,
					message=_("Row {0}: item_code {1} does not match PO line item_code {2}.").format(
						row_number, item_code, row.item_code
					),
				)
			]
		)
	return row


def validate_qty_within_remaining(
	*,
	purchase_order_item: str,
	qty: float,
	row_number: int,
	invoice_no: str | None,
	remaining_qty_by_name: dict[str, float],
):
	remaining = flt(remaining_qty_by_name.get(purchase_order_item, 0))
	if qty <= remaining:
		return
	raise PortalValidationError(
		[
			error_entry(
				row_number=row_number,
				field="qty",
				invoice_no=invoice_no,
				message=_("Row {0}: qty {1} exceeds remaining PO qty {2}.").format(
					row_number, qty, remaining
				),
			)
		]
	)


def normalize_group_value(value: str | None) -> str:
	return (value or "").strip()


def normalize_group_field(field: str, value: str | None) -> str:
	if field == "supplier_invoice_amount":
		raw = (value or "").strip()
		return "" if not raw else str(flt(raw))
	return normalize_group_value(value)


def enforce_bulk_limits(rows: list[ParsedBulkRow]):
	if len(rows) > MAX_BULK_ROWS:
		raise PortalValidationError(
			[
				error_entry(
					field="items_csv",
					message=_("Bulk upload supports up to {0} rows.").format(MAX_BULK_ROWS),
				)
			]
		)


def validate_bulk_group_count(invoice_groups: dict[str, list[ParsedBulkRow]]):
	if len(invoice_groups) <= MAX_BULK_INVOICES:
		return
	raise PortalValidationError(
		[
			error_entry(
				field="items_csv",
				message=_("Bulk upload supports up to {0} invoice groups.").format(MAX_BULK_INVOICES),
			)
		]
	)


def _invoice_group_compare_value(row: ParsedBulkRow, field: str) -> str:
	if field == "supplier_invoice_amount":
		return normalize_group_field("supplier_invoice_amount", str(row.supplier_invoice_amount))
	return normalize_group_field(field, getattr(row, field))


def validate_invoice_group_consistency(invoice_no: str, rows: list[ParsedBulkRow]):
	if not rows:
		return

	base = {field: _invoice_group_compare_value(rows[0], field) for field in INVOICE_GROUP_FIELDS}
	errors: list[dict] = []
	for row in rows[1:]:
		for field in INVOICE_GROUP_FIELDS:
			current = _invoice_group_compare_value(row, field)
			if current == base[field]:
				continue
			errors.append(
				error_entry(
					row_number=row.row_number,
					invoice_no=invoice_no,
					field=field,
					message=_("Row {0}: {1} mismatch for invoice {2}; expected '{3}', found '{4}'.").format(
						row.row_number, field, invoice_no, base[field], current
					),
				)
			)

	if errors:
		raise PortalValidationError(errors)


def validate_no_duplicate_po_sr_no(rows: list[ParsedBulkRow], *, invoice_no: str):
	seen: set[tuple[str, str]] = set()
	errors: list[dict] = []
	for row in rows:
		key = (row.purchase_order, row.sr_no)
		if key not in seen:
			seen.add(key)
			continue
		errors.append(
			error_entry(
				row_number=row.row_number,
				invoice_no=invoice_no,
				field="sr_no",
				message=_("Row {0}: duplicate purchase_order + sr_no in invoice group {1}.").format(
					row.row_number, invoice_no
				),
			)
		)
	if errors:
		raise PortalValidationError(errors)


def validate_invoice_group_single_purchase_order(invoice_no: str, rows: list[ParsedBulkRow]):
	if not rows:
		return

	expected_po = rows[0].purchase_order
	errors: list[dict] = []
	for row in rows[1:]:
		if row.purchase_order == expected_po:
			continue
		errors.append(
			error_entry(
				row_number=row.row_number,
				invoice_no=invoice_no,
				field="purchase_order",
				message=_(
					"Row {0}: invoice group {1} must contain a single Purchase Order. Expected {2}, found {3}."
				).format(row.row_number, invoice_no, expected_po, row.purchase_order),
			)
		)

	if errors:
		raise PortalValidationError(errors)
