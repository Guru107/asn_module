import base64

import frappe
from frappe import _
from frappe.utils import flt, today


def fiscal_year_for_date(date: str, company: str | None = None) -> str | None:
	"""The enabled Fiscal Year that covers ``date``, scoped to ``company`` when given.

	When several fiscal years overlap, the one with the latest ``year_start_date`` wins.
	"""
	candidates = frappe.get_all(
		"Fiscal Year",
		filters={
			"disabled": 0,
			"year_start_date": ("<=", date),
			"year_end_date": (">=", date),
		},
		fields=["name"],
		order_by="year_start_date desc",
		limit_page_length=0,
	)
	if not candidates:
		return None
	if not (company or "").strip():
		return candidates[0]["name"]
	if not frappe.db.table_exists("Fiscal Year Company"):
		return candidates[0]["name"]
	company = company.strip()
	for row in candidates:
		fy_name = row["name"]
		linked = frappe.get_all("Fiscal Year Company", filters={"parent": fy_name}, pluck="company")
		if not linked or company in linked:
			return fy_name
	return None


def apply_site_document_requirements(doc) -> None:
	"""Fill the fields sites mark mandatory on a document built from scratch.

	For documents no mapper fills (a Purchase Return): a site that made
	``custom_fiscal_year`` or the ``taxes`` table mandatory (Property Setter /
	Custom Field) would reject the server-side insert. Taxes are copied from the
	linked Purchase Order -- the PO is the source of truth for an item's tax
	setup. Mapped documents inherit taxes and need only ``fill_custom_fiscal_year``.
	No-op where the site requires neither.
	"""
	fill_custom_fiscal_year(doc)
	_fill_taxes_from_purchase_order(doc)


def _fill_taxes_from_purchase_order(doc) -> None:
	"""Copy the linked PO's taxes rows onto a document built from scratch.

	Whole rows are copied so row references and print-rate flags survive;
	``calculate_taxes_and_totals`` recomputes every computed amount on validate
	except ``Actual`` rows, which get this document's share of the PO amount (a
	return's negative qty makes that share negative).
	"""
	meta = getattr(doc, "meta", None)
	field = meta.get_field("taxes") if meta else None
	if not field or not field.reqd or doc.get("taxes"):
		return

	po_names = sorted(
		{row.get("purchase_order") for row in doc.get("items") or [] if row.get("purchase_order")}
	)
	if not po_names:
		return
	if len(po_names) > 1:
		frappe.throw(
			_("Cannot pick taxes for this {0}: its items come from several Purchase Orders ({1})").format(
				doc.doctype, ", ".join(po_names)
			)
		)

	po = frappe.get_doc("Purchase Order", po_names[0])
	if not po.taxes:
		frappe.throw(
			_("Purchase Order {0} has no taxes to copy, and this site requires taxes on {1}").format(
				po.name, doc.doctype
			)
		)

	doc_amount = sum(flt(row.get("qty")) * flt(row.get("rate")) for row in doc.get("items"))
	share = doc_amount / flt(po.total) if flt(po.total) else 0
	for tax in po.taxes:
		row = tax.as_dict(no_default_fields=True)
		if row.charge_type == "Actual":
			row.tax_amount = flt(row.tax_amount) * share
		doc.append("taxes", row)


def fill_custom_fiscal_year(doc) -> None:
	"""Satisfy a site's mandatory Fiscal Year on a document the scan chain builds.

	Sites mark a ``custom_fiscal_year`` Link mandatory on receipts and invoices.
	A desk form fills it for a desk user, but the scan chain builds these documents
	server-side, where no form ever runs, and the insert then dies on the missing
	mandatory field. Fill it from the document's own posting date. No-op where the
	doctype does not carry the field or does not require it. A value that names a
	Fiscal Year this site actually has is kept; one that does not (a field default
	left behind by a fiscal-year rollover) is replaced, so a stale default cannot
	break the scan chain.
	"""
	meta = getattr(doc, "meta", None)
	field = meta.get_field("custom_fiscal_year") if meta else None
	if not field or not field.reqd:
		return
	existing = (doc.get("custom_fiscal_year") or "").strip()
	if existing and frappe.db.exists("Fiscal Year", existing):
		return
	date = doc.get("posting_date") or doc.get("transaction_date") or today()
	fiscal_year = fiscal_year_for_date(date, company=doc.get("company"))
	if fiscal_year:
		doc.custom_fiscal_year = fiscal_year


def _scan_code_file_name(scan_result: dict, kind: str) -> str:
	"""Build ``{scan_code}-{kind}.png`` for a QR or barcode image."""
	from asn_module.qr_engine.scan_codes import format_scan_code_for_display

	if kind not in ("qr", "barcode"):
		frappe.throw(_("Scan image kind must be qr or barcode"))
	raw = (scan_result.get("human_readable") or scan_result.get("scan_code") or "").strip()
	label = format_scan_code_for_display(raw) if raw else ""
	if not label:
		frappe.throw(_("Scan image attachment requires a scan code"))
	return f"{label}-{kind}.png"


def attach_qr_to_doc(doc, scan_result, kind: str) -> None:
	"""Attach a generated QR or barcode PNG; ``file_name`` is the scan code."""
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": _scan_code_file_name(scan_result, kind),
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"content": base64.b64decode(scan_result["image_base64"]),
			"is_private": 0,
		}
	).save(ignore_permissions=True)


def _scan_attachment_exists(doc, file_name: str) -> bool:
	return bool(
		frappe.db.exists(
			"File",
			{
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"file_name": file_name,
			},
		)
	)


def attach_scan_codes_to_doc(doc, action: str) -> None:
	"""Attach the QR and barcode that create this document's successor.

	Both images carry one scan code: ``resolve_scan_code_for_attachment`` shares a
	registry row per (action, source) pair, so a QR scan and a barcode scan
	of the same printed document dispatch the same action. File names use the
	scan code (``{code}-qr.png`` and ``{code}-barcode.png``). Skips files that
	already exist so backfill is safe after submit or partial attachment.
	"""
	from asn_module.qr_engine.generate import generate_barcode, generate_qr

	qr_result = generate_qr(action=action, source_doctype=doc.doctype, source_name=doc.name)
	qr_file_name = _scan_code_file_name(qr_result, "qr")
	if not _scan_attachment_exists(doc, qr_file_name):
		attach_qr_to_doc(doc, qr_result, "qr")
	barcode_result = generate_barcode(action=action, source_doctype=doc.doctype, source_name=doc.name)
	barcode_file_name = _scan_code_file_name(barcode_result, "barcode")
	if not _scan_attachment_exists(doc, barcode_file_name):
		attach_qr_to_doc(doc, barcode_result, "barcode")


@frappe.whitelist()
def backfill_scan_code_attachments(doctype: str, name: str, action: str) -> dict:
	"""Attach missing QR/barcode files for an existing registry row (Administrator)."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc(doctype, name)
	attach_scan_codes_to_doc(doc, action)
	files = frappe.get_list(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["file_name"],
		order_by="creation desc",
		limit_page_length=0,
	)
	return {
		"doctype": doctype,
		"name": name,
		"action": action,
		"files": [row["file_name"] for row in files],
	}


def find_pr_row_for_qi(qi, purchase_receipt):
	"""Resolve the Purchase Receipt row a Quality Inspection refers to.

	Prefers the explicit ``purchase_receipt_item`` link; falls back to a single item-code
	match, throws if ambiguous or missing.
	"""
	qi_pr_item = getattr(qi, "purchase_receipt_item", None)
	if qi_pr_item:
		for item in purchase_receipt.items:
			if item.name == qi_pr_item:
				return item

	matching_rows = [item for item in purchase_receipt.items if item.item_code == qi.item_code]
	if len(matching_rows) == 1:
		return matching_rows[0]
	if len(matching_rows) > 1:
		frappe.throw(
			_(
				"Multiple Purchase Receipt rows found for item {0} in {1}. "
				"Set a specific purchase_receipt_item on Quality Inspection {2}."
			).format(qi.item_code, qi.reference_name, qi.name)
		)

	frappe.throw(_("Item {0} not found in {1}").format(qi.item_code, qi.reference_name))
