from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.exceptions import ValidationError as FrappeValidationError
from frappe.utils import cstr
from frappe.website.utils import cleanup_page_name

from asn_module.templates.pages.asn import _get_supplier_for_user, get_open_purchase_orders_for_supplier
from asn_module.templates.pages.asn_new_services import (
	BULK_CSV_HEADERS,
	ParsedBulkRow,
	ParsedSingleRow,
	PortalValidationError,
	create_bulk_asns_for_supplier,
	error_entry,
	fetch_purchase_order_items,
	insert_and_submit_asn,
	parse_bulk_csv_content,
	parse_non_negative_rate,
	parse_positive_qty,
	resolve_po_item,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
	validate_supplier_invoices_not_reused,
)

ALLOWED_MODES = {"single", "bulk"}


@dataclass
class CreateResult:
	asn_names: list[str]


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.title = "New ASN"
	context.active_tab = "single"
	context.single_errors = []
	context.bulk_errors = []
	context.bulk_success = None
	context.bulk_csv_headers = BULK_CSV_HEADERS

	user = frappe.session.user
	supplier = _get_supplier_for_user(user)
	if not supplier:
		frappe.throw(_("Only supplier portal users can create ASNs."), frappe.PermissionError)

	context.supplier = supplier
	context.open_purchase_orders = get_open_purchase_orders_for_supplier(supplier)

	if not frappe.request or frappe.request.method != "POST":
		return

	mode = (frappe.form_dict.get("mode") or "").strip()
	context.active_tab = mode if mode in ALLOWED_MODES else "single"

	try:
		if mode == "single":
			result = _create_single_asn(supplier)
			route = frappe.db.get_value("ASN", result.asn_names[0], "route") or _default_asn_route(
				result.asn_names[0]
			)
			frappe.local.flags.redirect_location = f"/{route.lstrip('/')}"
			raise frappe.Redirect
		if mode == "bulk":
			result = _create_bulk_asns(supplier)
			context.bulk_success = _("Created and submitted {0} ASN(s): {1}").format(
				len(result.asn_names), ", ".join(result.asn_names)
			)
			context.active_tab = "bulk"
			return
		raise PortalValidationError([error_entry(field="mode", message=_("Invalid submit mode."))])
	except PortalValidationError as exc:
		if context.active_tab == "bulk":
			context.bulk_errors = exc.errors
		else:
			context.single_errors = exc.errors
	except FrappeValidationError as exc:
		msg = cstr(getattr(exc, "message", None) or (exc.args[0] if exc.args else "") or exc).strip()
		if not msg:
			msg = _("We could not save your notice. Please check the form and try again.")
		entry = error_entry(message=msg, field="asn")
		if context.active_tab == "bulk":
			context.bulk_errors = [entry]
		else:
			context.single_errors = [entry]


def _create_single_asn(supplier: str) -> CreateResult:
	selected_purchase_orders = _request_list("selected_purchase_orders")
	validate_selected_purchase_orders(
		supplier=supplier,
		selected_purchase_orders=selected_purchase_orders,
		field="selected_purchase_orders",
	)
	if len(selected_purchase_orders) != 1:
		raise PortalValidationError(
			[
				error_entry(
					field="selected_purchase_orders",
					message=_("Select exactly one open Purchase Order for Single ASN."),
				)
			]
		)
	validate_supplier_invoices_not_reused(supplier, [_request_value("supplier_invoice_no")])
	rows = _parse_single_rows()
	if not rows:
		raise PortalValidationError(
			[
				error_entry(
					field="rows",
					message=_("Add at least one manual row for Single ASN."),
				)
			]
		)

	rows_by_key, remaining_qty_by_name = fetch_purchase_order_items(selected_purchase_orders)
	running_remaining = dict(remaining_qty_by_name)
	items = []
	seen_po_sr: set[tuple[str, str]] = set()
	for row in rows:
		if row.purchase_order not in selected_purchase_orders:
			raise PortalValidationError(
				[
					error_entry(
						row_number=row.row_number,
						field="purchase_order",
						message=_("Manual row {0}: Purchase Order is not selected.").format(row.row_number),
					)
				]
			)
		if (row.purchase_order, row.sr_no) in seen_po_sr:
			raise PortalValidationError(
				[
					error_entry(
						row_number=row.row_number,
						field="sr_no",
						message=_("Manual row {0}: duplicate purchase_order + sr_no is not allowed.").format(
							row.row_number
						),
					)
				]
			)
		seen_po_sr.add((row.purchase_order, row.sr_no))

		po_item = resolve_po_item(
			purchase_order=row.purchase_order,
			sr_no=row.sr_no,
			item_code=row.item_code,
			row_number=row.row_number,
			invoice_no=None,
			rows_by_key=rows_by_key,
		)
		validate_qty_within_remaining(
			purchase_order_item=po_item.name,
			qty=row.qty,
			row_number=row.row_number,
			invoice_no=None,
			remaining_qty_by_name=running_remaining,
		)
		running_remaining[po_item.name] = frappe.utils.flt(
			running_remaining.get(po_item.name, 0)
		) - frappe.utils.flt(row.qty)
		items.append(
			{
				"purchase_order": row.purchase_order,
				"purchase_order_item": po_item.name,
				"item_code": row.item_code,
				"uom": row.uom or po_item.uom,
				"qty": row.qty,
				"rate": row.rate,
			}
		)

	asn = _insert_and_submit_asn(
		supplier=supplier,
		header={
			"supplier_invoice_no": _request_value("supplier_invoice_no"),
			"supplier_invoice_date": _request_value("supplier_invoice_date"),
			"expected_delivery_date": _request_value("expected_delivery_date"),
			"lr_no": _request_value("lr_no"),
			"lr_date": _request_value("lr_date"),
			"transporter_name": _request_value("transporter_name"),
			"vehicle_number": _request_value("vehicle_number"),
			"driver_contact": _request_value("driver_contact"),
			"supplier_invoice_amount": _request_supplier_invoice_amount(),
		},
		items=items,
	)
	return CreateResult(asn_names=[asn.name])


def _create_bulk_asns(supplier: str) -> CreateResult:
	rows = _parse_bulk_csv_rows()
	asn_names = create_bulk_asns_for_supplier(supplier, rows, insert_asn=_insert_and_submit_asn)
	return CreateResult(asn_names=asn_names)


def _insert_and_submit_asn(*, supplier: str, header: dict, items: list[dict]):
	return insert_and_submit_asn(supplier=supplier, header=header, items=items)


def _parse_single_rows() -> list[ParsedSingleRow]:
	po_values = _request_list("single_manual_purchase_order")
	sr_values = _request_list("single_manual_sr_no")
	item_values = _request_list("single_manual_item_code")
	uom_values = _request_list("single_manual_uom")
	qty_values = _request_list("single_manual_qty")
	rate_values = _request_list("single_manual_rate")

	max_len = max(
		len(po_values),
		len(sr_values),
		len(item_values),
		len(uom_values),
		len(qty_values),
		len(rate_values),
	)
	rows: list[ParsedSingleRow] = []
	errors: list[dict] = []
	for idx in range(max_len):
		row_number = idx + 1
		po = _safe_get(po_values, idx).strip()
		sr_no = _safe_get(sr_values, idx).strip()
		item_code = _safe_get(item_values, idx).strip()
		uom = _safe_get(uom_values, idx).strip()
		qty_raw = _safe_get(qty_values, idx).strip()
		rate_raw = _safe_get(rate_values, idx).strip()
		if not any([po, sr_no, item_code, uom, qty_raw, rate_raw]):
			continue

		missing = []
		if not po:
			missing.append("purchase_order")
		if not sr_no:
			missing.append("sr_no")
		if not item_code:
			missing.append("item_code")
		if not qty_raw:
			missing.append("qty")
		if not rate_raw:
			missing.append("rate")
		if missing:
			errors.append(
				error_entry(
					row_number=row_number,
					field="row",
					message=_("Manual row {0}: Missing required fields: {1}.").format(
						row_number, ", ".join(missing)
					),
				)
			)
			continue

		try:
			qty = parse_positive_qty(qty_raw, row_number=row_number, field="qty")
			rate = parse_non_negative_rate(rate_raw, row_number=row_number, field="rate")
		except PortalValidationError as exc:
			errors.extend(exc.errors)
			continue
		rows.append(
			ParsedSingleRow(
				row_number=row_number,
				purchase_order=po,
				sr_no=sr_no,
				item_code=item_code,
				uom=uom,
				qty=qty,
				rate=rate,
			)
		)

	if errors:
		raise PortalValidationError(errors)
	return rows


def _parse_bulk_csv_rows() -> list[ParsedBulkRow]:
	file_storage = (frappe.request.files or {}).get("bulk_items_csv") if frappe.request else None
	if not file_storage or not getattr(file_storage, "filename", ""):
		return []

	content = file_storage.stream.read()
	return parse_bulk_csv_content(content)


def _request_list(fieldname: str) -> list[str]:
	if not frappe.request:
		return []
	return [value.strip() for value in frappe.request.form.getlist(fieldname) if (value or "").strip()]


def _request_value(fieldname: str) -> str:
	return (frappe.form_dict.get(fieldname) or "").strip()


def _request_supplier_invoice_amount() -> float:
	raw = (frappe.form_dict.get("supplier_invoice_amount") or "").strip()
	if not raw:
		raise PortalValidationError(
			[
				error_entry(
					field="supplier_invoice_amount",
					message=_("Supplier invoice amount is required."),
				)
			]
		)
	val = frappe.utils.flt(raw)
	if val < 0:
		raise PortalValidationError(
			[
				error_entry(
					field="supplier_invoice_amount",
					message=_("Supplier invoice amount cannot be negative."),
				)
			]
		)
	return val


def _safe_get(values: list[str], idx: int) -> str:
	if idx < len(values):
		return values[idx] or ""
	return ""


def _default_asn_route(asn_name: str) -> str:
	return f"asn/{cleanup_page_name(asn_name).replace('_', '-')}"
