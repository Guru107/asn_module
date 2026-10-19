"""Short opaque scan codes backed by the Scan Code doctype.

Current development policy intentionally supports only canonical 16-character
codes; legacy compatibility is out of scope unless explicitly requested.
"""

from __future__ import annotations

import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

# Uppercase compact alphabet without ambiguous characters (0/O, 1/I/L).
SCAN_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SCAN_CODE_LENGTH = 16

# Actions that may be executed when the registry row is already ``Used`` (re-scan).
RESCAN_SAFE_ACTIONS = frozenset({"confirm_putaway"})

_MAX_CREATE_ATTEMPTS = 64


def format_scan_code_for_display(code: str) -> str:
	"""Human-readable scan code as a plain uppercase string without separators."""
	raw = (code or "").replace("-", "").replace(" ", "").upper()
	if not raw:
		return ""
	return raw


def _random_scan_code_value() -> str:
	return "".join(secrets.choice(SCAN_CODE_ALPHABET) for _ in range(SCAN_CODE_LENGTH))


@frappe.whitelist()
def get_scan_code_length() -> int:
	"""Return canonical scan-code length for UI clients."""
	return SCAN_CODE_LENGTH


def get_or_create_scan_code(action_key: str, source_doctype: str, source_name: str) -> str:
	"""Return scan code (document name) for an active row, or create a new active row.

	QR and barcode generation for the same (action, source) pair share one registry row.
	"""
	action_key = (action_key or "").strip()
	source_doctype = (source_doctype or "").strip()
	source_name = (source_name or "").strip()
	if not action_key or not source_doctype or not source_name:
		raise frappe.ValidationError(
			_("Scan code registration requires action, source doctype, and source name")
		)

	existing = frappe.db.get_value(
		"Scan Code",
		{
			"action_key": action_key,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"status": "Active",
		},
		"name",
		order_by="creation desc",
	)
	if existing and normalize_scan_code(existing) == existing:
		return existing

	for _attempt in range(_MAX_CREATE_ATTEMPTS):
		value = _random_scan_code_value()
		if frappe.db.exists("Scan Code", value):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": value,
				"action_key": action_key,
				"source_doctype": source_doctype,
				"source_name": source_name,
				"status": "Active",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	frappe.throw(_("Could not allocate a unique scan code; try again."))


def get_scan_code_doc(code: str) -> frappe.model.document.Document | None:
	normalized = normalize_scan_code(code)
	if not normalized or not frappe.db.exists("Scan Code", normalized):
		return None
	return frappe.get_doc("Scan Code", normalized)


def normalize_scan_code(code: str | None) -> str:
	"""Normalize and validate a scan code in strict canonical 16-char form."""
	raw = (code or "").strip().replace(" ", "").upper()
	if len(raw) != SCAN_CODE_LENGTH:
		return ""
	if any(ch not in SCAN_CODE_ALPHABET for ch in raw):
		return ""
	return raw


def validate_scan_code_row(doc: frappe.model.document.Document, action_key: str) -> None:
	"""Validate status and re-scan rules."""
	if doc.status == "Used":
		if action_key in RESCAN_SAFE_ACTIONS:
			return
		frappe.throw(
			_("This scan code has already been used and cannot be scanned again."),
			title=_("Scan not allowed"),
		)

	if doc.status != "Active":
		frappe.throw(_("This scan code is not valid for scanning."), title=_("Scan not allowed"))


def record_successful_scan(doc_name: str, action_key: str) -> None:
	"""Update scan metadata and mark ``Used`` when the action is not re-scan-safe."""
	count = cint(frappe.db.get_value("Scan Code", doc_name, "scan_count"))
	frappe.db.set_value(
		"Scan Code",
		doc_name,
		{
			"scan_count": count + 1,
			"last_scanned_on": now_datetime(),
		},
		update_modified=True,
	)

	if action_key not in RESCAN_SAFE_ACTIONS:
		frappe.db.set_value("Scan Code", doc_name, "status", "Used", update_modified=True)


def purge_scan_codes_for_source(source_doctype: str, source_name: str) -> None:
	"""Delete Scan Code rows for a source document so trash is not blocked by Dynamic Link checks."""
	if not frappe.db.exists("DocType", "Scan Code"):
		return
	source_doctype = (source_doctype or "").strip()
	source_name = (source_name or "").strip()
	if not source_doctype or not source_name:
		return
	frappe.db.delete(
		"Scan Code",
		{"source_doctype": source_doctype, "source_name": source_name},
	)


def reactivate_scan_code(action_key: str, source_doctype: str, source_name: str) -> None:
	"""Mark a predecessor scan code Active again after a draft chain document is deleted."""
	if not frappe.db.exists("DocType", "Scan Code"):
		return
	action_key = (action_key or "").strip()
	source_doctype = (source_doctype or "").strip()
	source_name = (source_name or "").strip()
	if not action_key or not source_doctype or not source_name:
		return
	for code_name in frappe.get_all(
		"Scan Code",
		filters={
			"action_key": action_key,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"status": "Used",
		},
		pluck="name",
	):
		frappe.db.set_value("Scan Code", code_name, "status", "Active", update_modified=True)


def _asn_scan_actions() -> tuple[str, ...]:
	return ("create_purchase_receipt", "create_gate_pass_from_asn")


def reactivate_upstream_scan_codes_for_trashed_document(doc) -> None:
	"""Reactivate scan codes that fed this draft before purge deletes their Scan Log rows."""
	if cint(getattr(doc, "docstatus", 0)) == 1:
		return
	if not frappe.db.exists("DocType", "Scan Log"):
		return

	seen: set[tuple[str, str, str]] = set()
	for row in frappe.get_all(
		"Scan Log",
		filters={
			"result_doctype": doc.doctype,
			"result_name": doc.name,
			"result": "Success",
		},
		fields=["action", "source_doctype", "source_name"],
	):
		key = (row.action or "", row.source_doctype or "", row.source_name or "")
		if not all(key) or key in seen:
			continue
		seen.add(key)
		reactivate_scan_code(*key)

	def _field(fieldname: str) -> str:
		value = doc.get(fieldname) if hasattr(doc, "get") else getattr(doc, fieldname, None)
		return (value or "").strip()

	if doc.doctype == "Purchase Receipt":
		asn = _field("asn")
		if asn:
			for action_key in _asn_scan_actions():
				reactivate_scan_code(action_key, "ASN", asn)
		gate_pass = _field("custom_gate_pass_reference")
		if gate_pass:
			reactivate_scan_code("create_receipt_from_gate_pass", "Gate Pass", gate_pass)
		scr = _field("subcontracting_receipt")
		if scr:
			reactivate_scan_code("create_purchase_receipt_from_subcontracting_receipt", "Subcontracting Receipt", scr)
	elif doc.doctype == "Subcontracting Receipt":
		asn = _field("asn")
		if asn:
			for action_key in _asn_scan_actions():
				reactivate_scan_code(action_key, "ASN", asn)
	elif doc.doctype == "Gate Pass":
		asn = _field("asn")
		if asn:
			for action_key in _asn_scan_actions():
				reactivate_scan_code(action_key, "ASN", asn)


def purge_scan_logs_for_document(doctype: str, name: str) -> None:
	"""Delete Scan Log rows that reference a document as scan source or handler result."""
	if not frappe.db.exists("DocType", "Scan Log"):
		return
	doctype = (doctype or "").strip()
	name = (name or "").strip()
	if not doctype or not name:
		return
	frappe.db.delete("Scan Log", {"source_doctype": doctype, "source_name": name})
	frappe.db.delete("Scan Log", {"result_doctype": doctype, "result_name": name})


def purge_scan_registry_on_trash(doc, method=None) -> None:
	"""Remove scan registry rows before trash so Dynamic Link checks do not block delete.

	Runs for draft and cancelled documents (not submitted).
	"""
	del method
	if doc.doctype in ("Scan Code", "Scan Log"):
		return
	docstatus = cint(getattr(doc, "docstatus", 0))
	if docstatus == 1:
		return
	reactivate_upstream_scan_codes_for_trashed_document(doc)
	purge_scan_logs_for_document(doc.doctype, doc.name)
	purge_scan_codes_for_source(doc.doctype, doc.name)


def void_scan_codes(action_key: str, source_doctype: str, source_name: str) -> None:
	"""Mark every code for one (action, source) Voided so it cannot be scanned.

	``validate_scan_code_row`` refuses any status other than Active, so a
	voided code fails the scan with a clear message and the reopen path is
	closed as well. Codes are looked up row by row: ``db.set_value`` with a
	primary key stays supported across the Frappe versions this app runs on.
	"""
	filters = {
		"action_key": (action_key or "").strip(),
		"source_doctype": (source_doctype or "").strip(),
		"source_name": (source_name or "").strip(),
		"status": ("in", ("Active", "Used")),
	}
	for name in frappe.get_all("Scan Code", filters=filters, pluck="name"):
		frappe.db.set_value("Scan Code", name, "status", "Voided", update_modified=True)


def verify_registry_row_points_to_existing_source(doc: frappe.model.document.Document) -> bool:
	"""Return True if ``source_doctype`` / ``source_name`` resolves to an existing document."""
	try:
		if not doc.source_doctype or not doc.source_name:
			return False
		if not frappe.db.exists("DocType", doc.source_doctype):
			return False
		return bool(frappe.db.exists(doc.source_doctype, doc.source_name))
	except Exception:
		return False
