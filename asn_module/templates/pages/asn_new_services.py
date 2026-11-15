from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import escape_html, flt

from asn_module.asn_module.doctype.asn.asn import remaining_qty_by_purchase_order_item
from asn_module.stock_cap.api import asn_rows_cap_check, breaches_for_asn_rows
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures
from asn_module.templates.pages.asn import get_open_purchase_orders_for_supplier

OPEN_PO_STATUSES = ("To Receive", "To Receive and Bill")
MAX_BULK_ROWS = 5000
MAX_BULK_INVOICES = 500
# Errors shown for one upload; the rest are summed up in one line.
MAX_BULK_ERRORS = 50
BULK_ASN_JOB = "asn_module.templates.pages.asn_new_services.create_bulk_asns_job"
# Seconds: up to MAX_BULK_INVOICES inserts and submits, at most ~6 s each.
BULK_ASN_JOB_TIMEOUT = MAX_BULK_INVOICES * 6
BULK_CSV_HEADERS = [
	"supplier_invoice_no",
	"supplier_invoice_date",
	"expected_delivery_date",
	"lr_no",
	"lr_date",
	"transporter_name",
	"vehicle_number",
	"driver_contact",
	"supplier_invoice_amount",
	"purchase_order",
	"sr_no",
	"item_code",
	"qty",
	"rate",
]
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
	rate: float | None = None


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


def parse_bulk_csv_content(content: bytes) -> list[ParsedBulkRow]:
	try:
		text = content.decode("utf-8-sig")
	except UnicodeDecodeError as exc:
		raise PortalValidationError([error_entry(field="items_csv", message=str(exc))]) from exc

	reader = csv.DictReader(io.StringIO(text))
	if reader.fieldnames != BULK_CSV_HEADERS:
		raise PortalValidationError(
			[
				error_entry(
					field="items_csv",
					message=_("CSV headers must match exactly: {0}").format(", ".join(BULK_CSV_HEADERS)),
				)
			]
		)

	rows: list[ParsedBulkRow] = []
	errors: list[dict] = []
	for line_no, raw in enumerate(reader, start=2):
		if line_no - 1 > MAX_BULK_ROWS:
			_raise_too_many_rows()
		invoice_no = (raw.get("supplier_invoice_no") or "").strip()
		missing = []
		for field in ("supplier_invoice_no", "purchase_order", "sr_no", "item_code", "qty"):
			if (raw.get(field) or "").strip():
				continue
			missing.append(field)
		if missing:
			errors.append(
				error_entry(
					row_number=line_no,
					invoice_no=invoice_no or None,
					field="row",
					message=_("Row {0}: Missing required fields: {1}.").format(line_no, ", ".join(missing)),
				)
			)
			continue

		try:
			qty = parse_positive_qty(
				raw.get("qty") or "", row_number=line_no, field="qty", invoice_no=invoice_no
			)
			rate = parse_optional_non_negative_rate(
				raw.get("rate"), row_number=line_no, field="rate", invoice_no=invoice_no
			)
			supplier_invoice_amount = parse_required_supplier_invoice_amount(
				raw.get("supplier_invoice_amount"),
				row_number=line_no,
				invoice_no=invoice_no,
			)
		except PortalValidationError as exc:
			errors.extend(exc.errors)
			continue

		rows.append(
			ParsedBulkRow(
				row_number=line_no,
				supplier_invoice_no=invoice_no,
				supplier_invoice_date=(raw.get("supplier_invoice_date") or "").strip(),
				expected_delivery_date=(raw.get("expected_delivery_date") or "").strip(),
				lr_no=(raw.get("lr_no") or "").strip(),
				lr_date=(raw.get("lr_date") or "").strip(),
				transporter_name=(raw.get("transporter_name") or "").strip(),
				vehicle_number=(raw.get("vehicle_number") or "").strip(),
				driver_contact=(raw.get("driver_contact") or "").strip(),
				supplier_invoice_amount=supplier_invoice_amount,
				purchase_order=(raw.get("purchase_order") or "").strip(),
				sr_no=(raw.get("sr_no") or "").strip(),
				item_code=(raw.get("item_code") or "").strip(),
				qty=qty,
				rate=rate,
			)
		)

	if errors:
		raise PortalValidationError(bounded_errors(errors))
	return rows


def bounded_errors(errors: list[dict]) -> list[dict]:
	"""Keep the first MAX_BULK_ERRORS errors and say how many more there were."""
	if len(errors) <= MAX_BULK_ERRORS:
		return errors
	hidden = len(errors) - MAX_BULK_ERRORS
	return [
		*errors[:MAX_BULK_ERRORS],
		error_entry(
			field="bulk",
			message=_("{0} more errors are not shown. Fix the errors above and upload again.").format(hidden),
		),
	]


def validate_supplier_invoices_not_reused(
	supplier: str, invoice_numbers: list[str], exclude_asn_name: str | None = None
):
	"""Raise PortalValidationError if any invoice number is already on a non-cancelled ASN.

	``exclude_asn_name`` is the draft being resumed. The ASN controller already ignores
	that document in its own uniqueness check. This gate has to do the same, or the
	supplier cannot submit the draft under the invoice number already stored on it.

	One batched query for the whole list; a bulk CSV can carry 500 invoice numbers.
	"""
	requested = [inv for raw in invoice_numbers if (inv := (raw or "").strip())]
	if not requested:
		return
	filters = {
		"supplier": supplier,
		"supplier_invoice_no": ("in", sorted(set(requested))),
		"docstatus": ("!=", 2),
	}
	if exclude_asn_name:
		filters["name"] = ("!=", exclude_asn_name)
	reused = set(frappe.get_all("ASN", filters=filters, pluck="supplier_invoice_no"))
	errors: list[dict] = []
	for inv in requested:
		if inv not in reused:
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
	exclude_asn_name: str | None = None,
) -> tuple[dict[tuple[str, str], list[frappe._dict]], dict[str, float | None]]:
	if not purchase_orders:
		return {}, {}

	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": ["in", purchase_orders]},
		fields=["name", "parent", "idx", "item_code", "uom", "rate", "qty"],
		limit_page_length=0,
	)
	po_item_qty_by_name = {row.name: flt(row.qty) for row in rows}
	remaining_qty_by_name = remaining_qty_by_purchase_order_item(
		po_item_qty_by_name, exclude_asn_name=exclude_asn_name
	)

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
	remaining_qty_by_name: dict[str, float | None],
):
	remaining = remaining_qty_by_name.get(purchase_order_item, 0)
	if remaining is None or qty <= flt(remaining):
		return
	cap_message = _stock_cap_refusal_for_po_item(
		purchase_order_item=purchase_order_item,
		qty=qty,
		row_number=row_number,
	)
	raise PortalValidationError(
		[
			_over_remaining_error(
				row_number=row_number,
				invoice_no=invoice_no,
				qty=qty,
				remaining=remaining,
				cap_message=cap_message,
			)
		]
	)


def _over_remaining_error(
	*, row_number: int, invoice_no: str | None, qty: float, remaining: float, cap_message: str | None
) -> dict:
	"""A Stock Cap refusal explains the excess better than the Remaining Qty figure, so it wins."""
	return error_entry(
		row_number=row_number,
		field="qty",
		invoice_no=invoice_no,
		message=cap_message
		or _("Row {0}: qty {1} exceeds remaining PO qty {2}.").format(row_number, qty, remaining),
	)


def _stock_cap_refusal_for_po_item(*, purchase_order_item: str, qty: float, row_number: int) -> str | None:
	"""Plain-language cap refusal for portal suppliers when a row exceeds branch headroom."""
	po_item = frappe.db.get_value(
		"Purchase Order Item",
		purchase_order_item,
		["parent", "item_code"],
		as_dict=True,
	)
	if not po_item or not po_item.parent:
		return None
	rows = [
		{
			"idx": row_number,
			"purchase_order": po_item.parent,
			"purchase_order_item": purchase_order_item,
			"item_code": po_item.item_code,
			"qty": flt(qty),
		}
	]
	breaches, _accepted = breaches_for_asn_rows(rows)
	if not breaches:
		return None
	return format_breaches(breaches, detailed=may_see_stock_figures())


def consume_remaining_qty(
	remaining_qty_by_name: dict[str, float | None], purchase_order_item: str, qty: float
):
	"""Reduce the running ceiling after a row is accepted.

	``None`` is an uncapped unit-price line. Later rows on that line stay uncapped.
	"""
	remaining = remaining_qty_by_name.get(purchase_order_item, 0)
	if remaining is None:
		return
	remaining_qty_by_name[purchase_order_item] = flt(remaining) - flt(qty)


def normalize_group_value(value: str | None) -> str:
	return (value or "").strip()


def normalize_group_field(field: str, value: str | None) -> str:
	if field == "supplier_invoice_amount":
		raw = (value or "").strip()
		return "" if not raw else str(flt(raw))
	return normalize_group_value(value)


def enforce_bulk_limits(rows: list[ParsedBulkRow]):
	if len(rows) > MAX_BULK_ROWS:
		_raise_too_many_rows()


def _raise_too_many_rows():
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


def _invoice_header(row: ParsedBulkRow) -> dict:
	return {
		"supplier_invoice_no": row.supplier_invoice_no,
		"supplier_invoice_date": row.supplier_invoice_date,
		"expected_delivery_date": row.expected_delivery_date,
		"lr_no": row.lr_no,
		"lr_date": row.lr_date,
		"transporter_name": row.transporter_name,
		"vehicle_number": row.vehicle_number,
		"driver_contact": row.driver_contact,
		"supplier_invoice_amount": row.supplier_invoice_amount,
	}


def _resolve_bulk_rows(
	rows: list[ParsedBulkRow],
	rows_by_key: dict[tuple[str, str], list[frappe._dict]],
) -> tuple[list[tuple[ParsedBulkRow, frappe._dict]], list[dict]]:
	"""Match each row to its Purchase Order Item, in file order."""
	resolved: list[tuple[ParsedBulkRow, frappe._dict]] = []
	errors: list[dict] = []
	for row in sorted(rows, key=lambda item: item.row_number):
		try:
			po_item = resolve_po_item(
				purchase_order=row.purchase_order,
				sr_no=row.sr_no,
				item_code=row.item_code,
				row_number=row.row_number,
				invoice_no=row.supplier_invoice_no,
				rows_by_key=rows_by_key,
			)
		except PortalValidationError as exc:
			errors.extend(exc.errors)
			continue
		resolved.append((row, po_item))
	return resolved, errors


def _cap_check_row(row: ParsedBulkRow, po_item: frappe._dict) -> dict:
	# idx is the real CSV row_number, so a reported breach cites the row the supplier must fix.
	return {
		"idx": row.row_number,
		"purchase_order": row.purchase_order,
		"purchase_order_item": po_item.name,
		"item_code": row.item_code,
		"qty": row.qty,
	}


def _accept_rows_within_remaining(
	resolved: list[tuple[ParsedBulkRow, frappe._dict]],
	*,
	remaining_qty_by_name: dict[str, float | None],
	invoices_that_do_not_consume: set[str],
	cap_refusal: Callable[[dict], str | None],
) -> tuple[dict[str, list[tuple[ParsedBulkRow, frappe._dict]]], list[dict]]:
	"""Take Remaining Qty in file order. A row that does not fit leaves the figure unchanged.

	``invoices_that_do_not_consume`` are groups the Stock Cap has already refused. Their
	rows are still checked, so a real excess is reported, but they are not created and
	must not reduce what a later row sees. ``cap_refusal`` gives a row's own Stock Cap
	breach, if any, for the error on a row that exceeds Remaining Qty.
	"""
	running_remaining = dict(remaining_qty_by_name)
	accepted: dict[str, list[tuple[ParsedBulkRow, frappe._dict]]] = {}
	errors: list[dict] = []
	for row, po_item in resolved:
		remaining = running_remaining.get(po_item.name, 0)
		if remaining is not None and row.qty > flt(remaining):
			errors.append(
				_over_remaining_error(
					row_number=row.row_number,
					invoice_no=row.supplier_invoice_no,
					qty=row.qty,
					remaining=remaining,
					cap_message=cap_refusal(_cap_check_row(row, po_item)),
				)
			)
			continue
		if row.supplier_invoice_no in invoices_that_do_not_consume:
			continue
		consume_remaining_qty(running_remaining, po_item.name, row.qty)
		accepted.setdefault(row.supplier_invoice_no, []).append((row, po_item))
	return accepted, errors


def _payloads_for_accepted_rows(
	valid_groups: list[tuple[str, dict, list[ParsedBulkRow]]],
	accepted_by_invoice: dict[str, list[tuple[ParsedBulkRow, frappe._dict]]],
) -> list[tuple[dict, list[dict]]]:
	payloads: list[tuple[dict, list[dict]]] = []
	for invoice_no, header, _invoice_rows in valid_groups:
		accepted = accepted_by_invoice.get(invoice_no) or []
		if not accepted:
			continue
		items = []
		for row, po_item in accepted:
			item_rate = flt(row.rate) if row.rate is not None else flt(getattr(po_item, "rate", None))
			items.append(
				{
					"purchase_order": row.purchase_order,
					"purchase_order_item": po_item.name,
					"item_code": row.item_code,
					"uom": po_item.uom,
					"qty": row.qty,
					"rate": item_rate,
				}
			)
		payloads.append((header, items))
	return payloads


def create_bulk_asns_for_supplier(
	supplier: str,
	rows: list[ParsedBulkRow],
	insert_asn=None,
) -> list[str]:
	return insert_bulk_asns(supplier, validate_bulk_rows(supplier, rows), insert_asn=insert_asn)


def validate_bulk_rows(supplier: str, rows: list[ParsedBulkRow]) -> list[tuple[dict, list[dict]]]:
	"""Check a whole upload and return ``(header, items)`` for each ASN to create.

	Raises PortalValidationError with the problems found, so nothing is created. The
	number of queries does not grow with the number of rows or invoice groups.
	"""
	enforce_bulk_limits(rows)
	if not rows:
		raise PortalValidationError([error_entry(field="items_csv", message=_("Upload a CSV with rows."))])

	all_purchase_orders = sorted({row.purchase_order for row in rows})
	validate_selected_purchase_orders(
		supplier=supplier,
		selected_purchase_orders=all_purchase_orders,
		field="purchase_order",
	)

	invoice_groups: dict[str, list[ParsedBulkRow]] = {}
	for row in rows:
		invoice_groups.setdefault(row.supplier_invoice_no, []).append(row)
	validate_bulk_group_count(invoice_groups)
	validate_supplier_invoices_not_reused(supplier, sorted(invoice_groups.keys()))

	rows_by_key, remaining_qty_by_name = fetch_purchase_order_items(all_purchase_orders)
	errors: list[dict] = []
	valid_groups: list[tuple[str, dict, list[ParsedBulkRow]]] = []

	for invoice_no, invoice_rows in invoice_groups.items():
		try:
			validate_invoice_group_consistency(invoice_no, invoice_rows)
			validate_invoice_group_single_purchase_order(invoice_no, invoice_rows)
			validate_no_duplicate_po_sr_no(invoice_rows, invoice_no=invoice_no)
		except PortalValidationError as exc:
			errors.extend(exc.errors)
			continue

		valid_groups.append((invoice_no, _invoice_header(invoice_rows[0]), invoice_rows))

	candidate_rows = [row for _invoice_no, _header, invoice_rows in valid_groups for row in invoice_rows]
	resolved, resolve_errors = _resolve_bulk_rows(candidate_rows, rows_by_key)
	errors.extend(resolve_errors)

	# One set of cap reads for the whole upload; every check below evaluates against it.
	cap_check = asn_rows_cap_check([_cap_check_row(row, po_item) for row, po_item in resolved])
	# The caller's read permission on Item cannot change within one request.
	detailed = may_see_stock_figures()

	def cap_refusal(cap_row: dict) -> str | None:
		breaches, _accepted = cap_check([cap_row])
		return format_breaches(breaches, detailed=detailed) if breaches else None

	cap_errors = _collect_stock_cap_errors(resolved, cap_check, detailed)
	breaching_invoices = {error["invoice_no"] for error in cap_errors if error.get("invoice_no")}
	accepted_by_invoice, qty_errors = _accept_rows_within_remaining(
		resolved,
		remaining_qty_by_name=remaining_qty_by_name,
		invoices_that_do_not_consume=breaching_invoices,
		cap_refusal=cap_refusal,
	)
	errors.extend(qty_errors)
	errors.extend(cap_errors)

	if errors:
		raise PortalValidationError(
			[
				*bounded_errors(errors),
				error_entry(field="bulk", message=_("No ASNs created due to validation failures.")),
			]
		)
	return _payloads_for_accepted_rows(valid_groups, accepted_by_invoice)


def insert_bulk_asns(
	supplier: str,
	payloads: list[tuple[dict, list[dict]]],
	insert_asn=None,
) -> list[str]:
	# Desk upload: a refusal propagates and rolls the whole request back.
	insert_asn = insert_asn or insert_and_submit_asn
	return [insert_asn(supplier=supplier, header=header, items=items).name for header, items in payloads]


def create_bulk_asns_job(supplier: str, payloads: list[tuple[dict, list[dict]]], notify_user: str) -> None:
	"""Background half of a portal bulk upload: create the ASNs the request validated, then email the user.

	The ASN controller checks each one again on submit. A refusal or an unexpected error
	stops the run; the ASNs already submitted stay, and the email names them.
	"""
	asn_names: list[str] = []
	errors: list[dict] = []
	for header, items in payloads:
		try:
			asn = insert_and_submit_asn(supplier=supplier, header=header, items=items)
		except PortalValidationError as exc:
			errors = exc.errors
			break
		except Exception:
			# Job entry point: a caught error is not rolled back for us. Undo this ASN only;
			# the earlier ones are committed.
			frappe.db.rollback()
			frappe.log_error(title="ASN portal bulk upload job failed")
			errors = [
				error_entry(
					field="bulk",
					invoice_no=header.get("supplier_invoice_no"),
					message=_("Invoice {0}: ASN creation failed unexpectedly.").format(
						header.get("supplier_invoice_no")
					),
				)
			]
			break
		# Batch job: commit each ASN so a later failure, timeout or killed worker cannot undo
		# the ones already submitted, locks stay short, and a rerun sees their invoice numbers.
		frappe.db.commit()
		asn_names.append(asn.name)
	_email_bulk_result(notify_user, asn_names, errors)


def _email_bulk_result(user: str, asn_names: list[str], errors: list[dict]) -> None:
	lines = [_("Created and submitted {0} ASN(s): {1}").format(len(asn_names), ", ".join(asn_names) or "-")]
	if errors:
		lines.append(_("The remaining invoices were not created:"))
		lines.extend(error.get("message") or "" for error in errors)
	frappe.sendmail(
		recipients=[frappe.db.get_value("User", user, "email")],
		subject=_("Bulk ASN upload stopped") if errors else _("Bulk ASN upload finished"),
		message="<br>".join(escape_html(line) for line in lines),
	)


def _collect_stock_cap_errors(
	resolved: list[tuple[ParsedBulkRow, frappe._dict]],
	cap_check: Callable[..., tuple[list, dict[tuple[str, str], float]]],
	detailed: bool,
) -> list[dict]:
	"""Evaluate the cap per invoice group before any ASN is inserted.

	Headroom taken by an earlier breach-free group is carried forward so one upload
	cannot drive an item past its maximum across several ASNs. Only ``accepted``, the
	incoming quantities ``evaluate()`` itself counted, is folded in, and only for groups
	that came back breach-free.

	Message text goes through the same redaction gate as the ASN controller
	(``format_breaches(..., detailed=...)``): portal suppliers have no ``read`` permission
	on ``Item`` and must not see On Hand, In Transit, or Maximum Stock.
	"""
	rows_by_invoice: dict[str, list[dict]] = {}
	for row, po_item in resolved:
		rows_by_invoice.setdefault(row.supplier_invoice_no, []).append(_cap_check_row(row, po_item))

	consumed: dict[tuple[str, str], float] = {}
	errors: list[dict] = []
	for invoice_no, cap_rows in rows_by_invoice.items():
		breaches, accepted = cap_check(cap_rows, consumed=consumed)
		for breach in breaches:
			errors.append(
				error_entry(
					field="items_csv",
					invoice_no=invoice_no,
					message=format_breaches([breach], detailed=detailed),
					row_number=breach.row_idxs[0] if breach.row_idxs else None,
				)
			)

		if breaches:
			continue

		for key, qty in accepted.items():
			consumed[key] = consumed.get(key, 0.0) + qty

	return errors


def create_job_asn_for_supplier(
	supplier: str,
	subcontracting_order: str,
	header: dict,
	lines: list[dict] | None = None,
	asn_name: str | None = None,
):
	"""Raise a Job ASN for one open Subcontracting Order.

	The single-ASN page calls this when the form posts ``subcontracting_order``.
	Each line names that order's finished good. Shipped Qty is the line qty.
	``asn_name`` is this supplier's unsubmitted draft; that draft is updated.
	"""
	order_name = (subcontracting_order or "").strip()
	if not order_name:
		frappe.throw(_("Select one open Subcontracting Order."))

	sco = frappe.get_doc("Subcontracting Order", order_name)
	if sco.docstatus != 1 or (sco.status or "") in ("Completed", "Closed", "Cancelled"):
		frappe.throw(_("Subcontracting Order {0} is not open.").format(order_name))
	if sco.supplier != supplier:
		frappe.throw(_("Subcontracting Order {0} is not for this supplier.").format(order_name))

	finished_goods = {row.name: row for row in sco.items}
	requested = lines
	if not requested:
		requested = [
			{
				"subcontracting_order_item": row.name,
				"qty": flt(row.qty) - flt(row.received_qty),
			}
			for row in sco.items
			if flt(row.qty) - flt(row.received_qty) > 0
		]

	items = []
	for line in requested:
		item_name = (line.get("subcontracting_order_item") or "").strip()
		finished_good = finished_goods.get(item_name)
		if not finished_good:
			frappe.throw(_("Subcontracting Order line {0} is not on {1}.").format(item_name, order_name))
		items.append(
			{
				"subcontracting_order": sco.name,
				"subcontracting_order_item": finished_good.name,
				"item_code": finished_good.item_code,
				"uom": finished_good.stock_uom,
				"qty": flt(line.get("qty")),
				"rate": flt(line.get("rate")) if line.get("rate") is not None else flt(finished_good.rate),
			}
		)

	return insert_and_submit_asn(
		supplier=supplier,
		header=header,
		items=items,
		asn_name=asn_name,
		submit=False,
	)


def insert_and_submit_asn(
	*,
	supplier: str,
	header: dict,
	items: list[dict],
	asn_name: str | None = None,
	submit: bool = True,
):
	header_fields = {
		"supplier_invoice_no": header.get("supplier_invoice_no"),
		"supplier_invoice_date": header.get("supplier_invoice_date"),
		"expected_delivery_date": header.get("expected_delivery_date"),
		"lr_no": header.get("lr_no"),
		"lr_date": header.get("lr_date"),
		"transporter_name": header.get("transporter_name"),
		"vehicle_number": header.get("vehicle_number"),
		"driver_contact": header.get("driver_contact"),
		"supplier_invoice_amount": header["supplier_invoice_amount"],
		"draft_purchase_order": header.get("draft_purchase_order"),
	}
	if asn_name:
		asn = frappe.get_doc("ASN", asn_name)
		asn.supplier = supplier
		asn.update(header_fields)
		asn.items = []
		for item in items:
			asn.append("items", item)
	else:
		asn = frappe.get_doc({"doctype": "ASN", "supplier": supplier, "items": items, **header_fields})
	asn.flags.ignore_permissions = True
	if not submit:
		# A draft is for review and editing. Scan codes are created in on_submit.
		# Mandatory invoice number, items, and quantity are enforced on submit.
		asn.flags.ignore_mandatory = True
		for item in getattr(asn, "items", None) or []:
			item.flags.ignore_mandatory = True
		if asn_name:
			asn.save()
		else:
			asn.insert()
		return asn
	# Earlier invoice groups in this request are already submitted and must stay.
	# A savepoint undoes only this draft when submit is refused. PortalValidationError
	# is rendered as a form error, so the request itself commits; without the rollback
	# the draft would commit with it and block the invoice number.
	frappe.db.savepoint("asn_portal_submit")
	try:
		if asn_name:
			asn.save()
		else:
			asn.insert()
		asn.submit()
	except frappe.ValidationError as exc:
		try:
			frappe.db.rollback(save_point="asn_portal_submit")
		except Exception:
			frappe.log_error(
				title="ASN portal submit: failed to roll back orphaned draft",
				message=frappe.get_traceback(),
			)
		raise PortalValidationError([error_entry(field="items_csv", message=str(exc))]) from exc
	return asn
