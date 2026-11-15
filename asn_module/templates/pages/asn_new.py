from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.exceptions import ValidationError as FrappeValidationError
from frappe.utils import cint, cstr, flt
from frappe.website.utils import cleanup_page_name

from asn_module.templates.pages.asn import _get_supplier_for_user, get_open_purchase_orders_for_supplier
from asn_module.templates.pages.asn_new_search import supplier_draft_asn_name
from asn_module.templates.pages.asn_new_services import (
	BULK_ASN_JOB,
	BULK_ASN_JOB_TIMEOUT,
	BULK_CSV_HEADERS,
	ParsedBulkRow,
	ParsedSingleRow,
	PortalValidationError,
	consume_remaining_qty,
	create_job_asn_for_supplier,
	error_entry,
	fetch_purchase_order_items,
	insert_and_submit_asn,
	parse_bulk_csv_content,
	parse_optional_non_negative_rate,
	resolve_po_item,
	validate_bulk_rows,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
	validate_supplier_invoices_not_reused,
)

ALLOWED_MODES = {"single", "bulk"}


@dataclass
class CreateResult:
	asn_names: list[str]
	incomplete: bool = False


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
	context.asn_name = supplier_draft_asn_name(supplier, (frappe.form_dict or {}).get("asn_name")) or ""
	context.draft_form = portal_draft_form(supplier, context.asn_name)

	if not frappe.request or frappe.request.method != "POST":
		return

	mode = (frappe.form_dict.get("mode") or "").strip()
	context.active_tab = mode if mode in ALLOWED_MODES else "single"

	try:
		if mode == "single":
			result = _create_single_asn(supplier)
			asn_name = result.asn_names[0]
			if result.incomplete:
				# Stay on the form so an unfinished draft is still on screen after Save.
				frappe.local.flags.redirect_location = f"/asn_new?asn_name={asn_name}"
			else:
				stored_route = frappe.db.get_value("ASN", asn_name, "route")
				frappe.local.flags.redirect_location = f"/{_portal_asn_route(asn_name, stored_route)}"
			raise frappe.Redirect
		if mode == "bulk":
			queued = _queue_bulk_asns(supplier)
			context.bulk_success = _(
				"Your file passed validation. {0} ASN(s) are queued and will be created and submitted "
				"in the background. We will email you the result."
			).format(queued)
			context.active_tab = "bulk"
			return
		raise PortalValidationError([error_entry(field="mode", message=_("Invalid submit mode."))])
	except PortalValidationError as exc:
		errors = list(exc.errors)
		if context.active_tab == "bulk":
			context.bulk_errors = errors
		else:
			context.single_errors = errors
			_keep_posted_single_form(context)
	except FrappeValidationError as exc:
		msg = cstr(getattr(exc, "message", None) or (exc.args[0] if exc.args else "") or exc).strip()
		if not msg:
			msg = _("We could not save your notice. Please check the form and try again.")
		entry = error_entry(message=msg, field="asn")
		if context.active_tab == "bulk":
			context.bulk_errors = [entry]
		else:
			context.single_errors = [entry]
			_keep_posted_single_form(context)


def _create_single_asn(supplier: str) -> CreateResult:
	subcontracting_order = _posted_subcontracting_order()
	selected_purchase_orders = _request_list("selected_purchase_orders")
	if subcontracting_order and selected_purchase_orders:
		raise PortalValidationError(
			[
				error_entry(
					field="subcontracting_order",
					message=_("A notice cannot name both a Purchase Order and a Subcontracting Order."),
				)
			]
		)
	if subcontracting_order:
		return _create_job_asn(supplier, subcontracting_order)

	if len(selected_purchase_orders) > 1:
		raise PortalValidationError(
			[
				error_entry(
					field="selected_purchase_orders",
					message=_("Select exactly one open Purchase Order for Single ASN."),
				)
			]
		)
	rows = _parse_single_rows()
	if rows and len(selected_purchase_orders) != 1:
		raise PortalValidationError(
			[
				error_entry(
					field="selected_purchase_orders",
					message=_("Select exactly one open Purchase Order for Single ASN."),
				)
			]
		)
	if selected_purchase_orders:
		validate_selected_purchase_orders(
			supplier=supplier,
			selected_purchase_orders=selected_purchase_orders,
			field="selected_purchase_orders",
		)
	draft_name = supplier_draft_asn_name(supplier, _request_value("asn_name"))
	if draft_name and frappe.db.exists(
		"ASN Item", {"parent": draft_name, "subcontracting_order": ["is", "set"]}
	):
		# Saving here would replace the draft's Job ASN lines with this form's rows.
		raise PortalValidationError(
			[
				error_entry(
					field="subcontracting_order",
					message=_("ASN {0} is a Job ASN. Select its Subcontracting Order to save it.").format(
						draft_name
					),
				)
			]
		)
	validate_supplier_invoices_not_reused(
		supplier,
		[_request_value("supplier_invoice_no")],
		exclude_asn_name=draft_name,
	)

	items = []
	if rows:
		rows_by_key, remaining_qty_by_name = fetch_purchase_order_items(
			selected_purchase_orders,
			exclude_asn_name=draft_name,
		)
		running_remaining = dict(remaining_qty_by_name)
		seen_po_sr: set[tuple[str, str]] = set()
		for row in rows:
			if row.purchase_order not in selected_purchase_orders:
				raise PortalValidationError(
					[
						error_entry(
							row_number=row.row_number,
							field="purchase_order",
							message=_("Manual row {0}: Purchase Order is not selected.").format(
								row.row_number
							),
						)
					]
				)
			if (row.purchase_order, row.sr_no) in seen_po_sr:
				raise PortalValidationError(
					[
						error_entry(
							row_number=row.row_number,
							field="sr_no",
							message=_(
								"Manual row {0}: duplicate purchase_order + sr_no is not allowed."
							).format(row.row_number),
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
			if flt(row.qty) > 0:
				validate_qty_within_remaining(
					purchase_order_item=po_item.name,
					qty=row.qty,
					row_number=row.row_number,
					invoice_no=None,
					remaining_qty_by_name=running_remaining,
				)
				consume_remaining_qty(running_remaining, po_item.name, row.qty)
			items.append(
				{
					"purchase_order": row.purchase_order,
					"purchase_order_item": po_item.name,
					"item_code": row.item_code,
					"uom": row.uom or po_item.uom,
					"qty": row.qty,
					"rate": flt(po_item.rate) if row.rate is None else row.rate,
				}
			)

	header = _single_header(selected_purchase_orders[0] if selected_purchase_orders else "")
	asn = _insert_and_submit_asn(
		asn_name=draft_name,
		supplier=supplier,
		submit=False,
		header=header,
		items=items,
	)
	return CreateResult(asn_names=[asn.name], incomplete=not _single_draft_is_complete(header, items))


def _create_job_asn(supplier: str, subcontracting_order: str) -> CreateResult:
	header = _single_header("")
	asn = create_job_asn_for_supplier(
		supplier=supplier,
		subcontracting_order=subcontracting_order,
		header=header,
		lines=_job_asn_lines_from_request(),
		asn_name=supplier_draft_asn_name(supplier, _request_value("asn_name")),
	)
	return CreateResult(
		asn_names=[asn.name],
		incomplete=not _single_draft_is_complete(header, [row.as_dict() for row in asn.items]),
	)


def _job_asn_lines_from_request() -> list[dict] | None:
	"""Per-line shipped qty, when the request posts it.

	The supplier page posts only the Subcontracting Order. A normal save therefore
	ships each finished good's remaining qty. ``subcontracting_order_item`` and
	``job_asn_qty`` are read when a caller posts them.
	"""
	item_names = _request_row_list("subcontracting_order_item")
	qty_values = _request_row_list("job_asn_qty")
	if not any(item_names):
		return None
	lines = []
	for idx, item_name in enumerate(item_names):
		if not item_name:
			continue
		lines.append(
			{
				"subcontracting_order_item": item_name,
				"qty": flt(_safe_get(qty_values, idx) or 0),
			}
		)
	return lines


def _single_header(purchase_order: str = "") -> dict:
	return {
		"supplier_invoice_no": _request_value("supplier_invoice_no"),
		"supplier_invoice_date": _request_value("supplier_invoice_date"),
		"expected_delivery_date": _request_value("expected_delivery_date"),
		"lr_no": _request_value("lr_no"),
		"lr_date": _request_value("lr_date"),
		"transporter_name": _request_value("transporter_name"),
		"vehicle_number": _request_value("vehicle_number"),
		"driver_contact": _request_value("driver_contact"),
		"supplier_invoice_amount": _optional_supplier_invoice_amount(),
		"draft_purchase_order": purchase_order,
	}


def _single_draft_is_complete(header: dict, items: list[dict]) -> bool:
	if not (header.get("supplier_invoice_no") or "").strip():
		return False
	if not items:
		return False
	return all(flt(item.get("qty")) > 0 for item in items)


def _keep_posted_single_form(context) -> None:
	"""Put the submitted fields back on the page when Save does not stick."""
	posted = posted_single_draft_form()
	if posted:
		context.draft_form = posted


def portal_draft_form(supplier: str, asn_name: str | None) -> dict | None:
	"""Header and rows for the supplier's own unsubmitted notice, for the edit form."""
	name = (asn_name or "").strip()
	if not supplier or not name:
		return None
	doc = frappe.db.get_value(
		"ASN",
		name,
		[
			"name",
			"supplier",
			"docstatus",
			"supplier_invoice_no",
			"supplier_invoice_date",
			"expected_delivery_date",
			"supplier_invoice_amount",
			"lr_no",
			"lr_date",
			"transporter_name",
			"vehicle_number",
			"driver_contact",
			"draft_purchase_order",
		],
		as_dict=True,
	)
	if not doc or doc.supplier != supplier or cint(doc.docstatus) != 0:
		return None

	items = frappe.get_all(
		"ASN Item",
		filters={"parent": name},
		fields=[
			"purchase_order",
			"purchase_order_item",
			"subcontracting_order",
			"subcontracting_order_item",
			"item_code",
			"uom",
			"qty",
			"rate",
			"idx",
		],
		order_by="idx asc",
		limit_page_length=0,
	)
	sr_by_name = {}
	for order_item_doctype, order_item_names in (
		("Purchase Order Item", [row.purchase_order_item for row in items if row.purchase_order_item]),
		(
			"Subcontracting Order Item",
			[row.subcontracting_order_item for row in items if row.subcontracting_order_item],
		),
	):
		if not order_item_names:
			continue
		for row in frappe.get_all(
			order_item_doctype,
			filters={"name": ["in", order_item_names]},
			fields=["name", "idx"],
			limit_page_length=0,
		):
			sr_by_name[row.name] = str(row.idx)

	# A Job ASN names a Subcontracting Order; its rows are not Purchase Order rows.
	subcontracting_order = next((row.subcontracting_order for row in items if row.subcontracting_order), "")
	purchase_order = ""
	if not subcontracting_order:
		purchase_order = next((row.purchase_order for row in items if row.purchase_order), "")
		if not purchase_order:
			purchase_order = doc.draft_purchase_order or ""
	return {
		"supplier_invoice_no": doc.supplier_invoice_no or "",
		"supplier_invoice_date": _date_input(doc.supplier_invoice_date),
		"expected_delivery_date": _date_input(doc.expected_delivery_date),
		"supplier_invoice_amount": doc.supplier_invoice_amount,
		"lr_no": doc.lr_no or "",
		"lr_date": _date_input(doc.lr_date),
		"transporter_name": doc.transporter_name or "",
		"vehicle_number": doc.vehicle_number or "",
		"driver_contact": doc.driver_contact or "",
		"purchase_order": purchase_order,
		"subcontracting_order": subcontracting_order,
		"rows": [
			{
				"sr_no": sr_by_name.get(row.subcontracting_order_item or row.purchase_order_item, ""),
				"item_code": row.item_code,
				"uom": row.uom or "",
				"qty": row.qty,
				"rate": row.rate,
				"subcontracting_order_item": row.subcontracting_order_item or "",
			}
			for row in items
			if (row.subcontracting_order or "") == subcontracting_order
			and (subcontracting_order or row.purchase_order == purchase_order)
		],
	}


def _date_input(value) -> str:
	if not value:
		return ""
	return str(value)[:10]


def _queue_bulk_asns(supplier: str) -> int:
	"""Validate the upload here, so errors show on the page; create the ASNs in a job."""
	payloads = validate_bulk_rows(supplier, _parse_bulk_csv_rows())
	frappe.enqueue(
		BULK_ASN_JOB,
		queue="long",
		timeout=BULK_ASN_JOB_TIMEOUT,
		enqueue_after_commit=True,
		supplier=supplier,
		payloads=payloads,
		notify_user=frappe.session.user,
	)
	return len(payloads)


def _insert_and_submit_asn(
	*,
	supplier: str,
	header: dict,
	items: list[dict],
	asn_name: str | None = None,
	submit: bool = True,
):
	return insert_and_submit_asn(
		supplier=supplier, header=header, items=items, asn_name=asn_name, submit=submit
	)


def _parse_draft_qty(qty_raw: str, *, row_number: int) -> float:
	"""Blank or zero quantity is allowed on a draft. A negative quantity is not."""
	if not (qty_raw or "").strip():
		return 0.0
	qty = flt(qty_raw)
	if qty < 0:
		raise PortalValidationError(
			[
				error_entry(
					row_number=row_number,
					field="qty",
					message=_("Row {0}: qty cannot be negative.").format(row_number),
				)
			]
		)
	return qty


def posted_single_draft_form() -> dict | None:
	"""Fields the supplier just posted, so a failed Save can render them again."""
	request = getattr(frappe, "request", None)
	form = getattr(request, "form", None) if request else None
	if form is None or not hasattr(form, "getlist"):
		return None

	po_values = _request_row_list("single_manual_purchase_order")
	sr_values = _request_row_list("single_manual_sr_no")
	item_values = _request_row_list("single_manual_item_code")
	uom_values = _request_row_list("single_manual_uom")
	qty_values = _request_row_list("single_manual_qty")
	rate_values = _request_row_list("single_manual_rate")
	selected = _request_list("selected_purchase_orders")
	max_len = max(
		len(po_values),
		len(sr_values),
		len(item_values),
		len(uom_values),
		len(qty_values),
		len(rate_values),
		0,
	)
	rows = []
	for idx in range(max_len):
		sr_no = _safe_get(sr_values, idx).strip()
		item_code = _safe_get(item_values, idx).strip()
		uom = _safe_get(uom_values, idx).strip()
		qty = _safe_get(qty_values, idx).strip()
		rate = _safe_get(rate_values, idx).strip()
		if not any([sr_no, item_code, uom, qty, rate]):
			continue
		rows.append(
			{
				"sr_no": sr_no,
				"item_code": item_code,
				"uom": uom,
				"qty": qty,
				"rate": rate,
			}
		)
	return {
		"supplier_invoice_no": _request_value("supplier_invoice_no"),
		"supplier_invoice_date": _request_value("supplier_invoice_date"),
		"expected_delivery_date": _request_value("expected_delivery_date"),
		"supplier_invoice_amount": _request_value("supplier_invoice_amount"),
		"lr_no": _request_value("lr_no"),
		"lr_date": _request_value("lr_date"),
		"transporter_name": _request_value("transporter_name"),
		"vehicle_number": _request_value("vehicle_number"),
		"driver_contact": _request_value("driver_contact"),
		"purchase_order": selected[0] if len(selected) == 1 else "",
		"rows": rows,
	}


def _parse_single_rows() -> list[ParsedSingleRow]:
	po_values = _request_row_list("single_manual_purchase_order")
	sr_values = _request_row_list("single_manual_sr_no")
	item_values = _request_row_list("single_manual_item_code")
	uom_values = _request_row_list("single_manual_uom")
	qty_values = _request_row_list("single_manual_qty")
	rate_values = _request_row_list("single_manual_rate")

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
			qty = _parse_draft_qty(qty_raw, row_number=row_number)
			rate = parse_optional_non_negative_rate(rate_raw, row_number=row_number, field="rate")
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


def _request_row_list(fieldname: str) -> list[str]:
	"""Keep blank cells so each manual row stays aligned with its neighbours."""
	if not frappe.request:
		return []
	return [(value or "").strip() for value in frappe.request.form.getlist(fieldname)]


def _request_value(fieldname: str) -> str:
	return (frappe.form_dict.get(fieldname) or "").strip()


def _posted_subcontracting_order() -> str:
	"""The Subcontracting Order field, only when the form actually posted it.

	``_request_value`` is the shared header reader. A Job ASN is a different
	submit, so a missing key stays on the Purchase Order path.
	"""
	form_dict = getattr(frappe, "form_dict", None) or {}
	if "subcontracting_order" not in form_dict:
		return ""
	return (form_dict.get("subcontracting_order") or "").strip()


def _optional_supplier_invoice_amount() -> float:
	"""Posted amount, or 0 when the field is still empty so the document can fill it."""
	raw = _request_value("supplier_invoice_amount")
	if not raw:
		return 0.0
	val = flt(raw)
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


def _portal_asn_route(asn_name: str, stored_route: str | None = None) -> str:
	"""Detail path under /asn/…, even when WebsiteGenerator stored a bare slug.

	With an empty DocType-level route, WebsiteGenerator.make_route() returns only the
	scrubbed name (e.g. asn-0002). Portal links and the post-submit redirect still need
	the asn/ prefix so they do not collide with other top-level website pages.
	"""
	route = (stored_route or "").strip().strip("/")
	if route.startswith("asn/"):
		return route
	return _default_asn_route(asn_name)
