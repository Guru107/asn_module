from __future__ import annotations

import frappe
from frappe import _

from asn_module.templates.pages.asn_new_services import (
	BULK_CSV_HEADERS,
	PortalValidationError,
	create_bulk_asns_for_supplier,
	parse_bulk_csv_content,
)


@frappe.whitelist()
def get_bulk_csv_headers() -> list[str]:
	_require_desk_bulk_permissions()
	return BULK_CSV_HEADERS


@frappe.whitelist()
def create_from_csv_file(file_url: str, supplier: str) -> dict:
	_require_desk_bulk_permissions()
	if not (file_url or "").strip():
		frappe.throw(_("Upload a CSV file before creating ASNs."), frappe.ValidationError)
	if not (supplier or "").strip():
		frappe.throw(_("Supplier is required."), frappe.ValidationError)

	try:
		rows = parse_bulk_csv_content(_read_file_content(file_url))
		asn_names = create_bulk_asns_for_supplier(supplier, rows)
	except PortalValidationError as exc:
		frappe.throw(_format_validation_errors(exc.errors), frappe.ValidationError)

	return {"asn_names": asn_names, "created_count": len(asn_names)}


def _require_desk_bulk_permissions():
	if frappe.has_permission("ASN", "create") and frappe.has_permission("ASN", "submit"):
		return
	frappe.throw(_("You need create and submit permission on ASN to use bulk upload."), frappe.PermissionError)


def _read_file_content(file_url: str) -> bytes:
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()
	if isinstance(content, bytes):
		return content
	return (content or "").encode()


def _format_validation_errors(errors: list[dict]) -> str:
	messages = []
	for error in errors:
		message = (error.get("message") or "").strip()
		if message:
			messages.append(message)
	if not messages:
		return _("Bulk upload failed. No ASNs created.")
	return "<br>".join(frappe.utils.escape_html(message) for message in messages)
