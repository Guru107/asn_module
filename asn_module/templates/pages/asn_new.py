from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.exceptions import ValidationError as FrappeValidationError
from frappe.utils import cstr
from frappe.website.utils import cleanup_page_name

from asn_module.templates.pages.asn import _get_supplier_for_user, get_open_purchase_orders_for_supplier
from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	ParsedSingleRow,
	PortalValidationError,
	enforce_bulk_limits,
	error_entry,
	fetch_purchase_order_items,
	parse_non_negative_rate,
	parse_optional_non_negative_rate,
	parse_positive_qty,
	parse_required_supplier_invoice_amount,
	resolve_po_item,
	validate_bulk_group_count,
	validate_invoice_group_consistency,
	validate_no_duplicate_po_sr_no,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
	validate_supplier_invoices_not_reused,
)

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
	enforce_bulk_limits(rows)
	if not rows:
		raise PortalValidationError([error_entry(field="items_csv", message=_("Upload a CSV with rows."))])

	all_purchase_orders = sorted({row.purchase_order for row in rows})
	validate_selected_purchase_orders(
		supplier=supplier,
		selected_purchase_orders=all_purchase_orders,
		field="purchase_order",
	)

	invoice_groups: dict[str, list[ParsedBulkRow]] = defaultdict(list)
	for row in rows:
		invoice_groups[row.supplier_invoice_no].append(row)
	validate_bulk_group_count(invoice_groups)
	validate_supplier_invoices_not_reused(supplier, sorted(invoice_groups.keys()))

	rows_by_key, remaining_qty_by_name = fetch_purchase_order_items(all_purchase_orders)
	running_remaining = dict(remaining_qty_by_name)
	errors: list[dict] = []
	asn_payloads: list[tuple[dict, list[dict]]] = []

	for invoice_no, invoice_rows in invoice_groups.items():
		try:
			validate_invoice_group_consistency(invoice_no, invoice_rows)
			validate_no_duplicate_po_sr_no(invoice_rows, invoice_no=invoice_no)
		except PortalValidationError as exc:
			errors.extend(exc.errors)
			continue

		header = {
			"supplier_invoice_no": invoice_rows[0].supplier_invoice_no,
			"supplier_invoice_date": invoice_rows[0].supplier_invoice_date,
			"expected_delivery_date": invoice_rows[0].expected_delivery_date,
			"lr_no": invoice_rows[0].lr_no,
			"lr_date": invoice_rows[0].lr_date,
			"transporter_name": invoice_rows[0].transporter_name,
			"vehicle_number": invoice_rows[0].vehicle_number,
			"driver_contact": invoice_rows[0].driver_contact,
			"supplier_invoice_amount": invoice_rows[0].supplier_invoice_amount,
		}
		items = []
		for row in invoice_rows:
			try:
				po_item = resolve_po_item(
					purchase_order=row.purchase_order,
					sr_no=row.sr_no,
					item_code=row.item_code,
					row_number=row.row_number,
					invoice_no=invoice_no,
					rows_by_key=rows_by_key,
				)
				validate_qty_within_remaining(
					purchase_order_item=po_item.name,
					qty=row.qty,
					row_number=row.row_number,
					invoice_no=invoice_no,
					remaining_qty_by_name=running_remaining,
				)
				running_remaining[po_item.name] = frappe.utils.flt(
					running_remaining.get(po_item.name, 0)
				) - frappe.utils.flt(row.qty)
				item_rate = (
					frappe.utils.flt(row.rate)
					if row.rate is not None
					else frappe.utils.flt(getattr(po_item, "rate", None))
				)
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
			except PortalValidationError as exc:
				errors.extend(exc.errors)
		if items:
			asn_payloads.append((header, items))

	if errors:
		errors.append(error_entry(field="bulk", message=_("No ASNs created due to validation failures.")))
		raise PortalValidationError(errors)

	asn_names = []
	for header, items in asn_payloads:
		asn = _insert_and_submit_asn(supplier=supplier, header=header, items=items)
		asn_names.append(asn.name)
	return CreateResult(asn_names=asn_names)


def _insert_and_submit_asn(*, supplier: str, header: dict, items: list[dict]):
	doc_payload = {
		"doctype": "ASN",
		"supplier": supplier,
		"supplier_invoice_no": header.get("supplier_invoice_no"),
		"supplier_invoice_date": header.get("supplier_invoice_date"),
		"expected_delivery_date": header.get("expected_delivery_date"),
		"lr_no": header.get("lr_no"),
		"lr_date": header.get("lr_date"),
		"transporter_name": header.get("transporter_name"),
		"vehicle_number": header.get("vehicle_number"),
		"driver_contact": header.get("driver_contact"),
		"items": items,
	}
	doc_payload["supplier_invoice_amount"] = header["supplier_invoice_amount"]
	asn = frappe.get_doc(doc_payload)
	asn.flags.ignore_permissions = True
	asn.insert(ignore_permissions=True)
	asn.flags.ignore_permissions = True
	asn.submit()
	return asn


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
		raise PortalValidationError(errors)
	return rows


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
