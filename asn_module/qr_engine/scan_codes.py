"""Short opaque scan codes backed by the Scan Code doctype.

Current development policy intentionally supports only canonical 16-character
codes; legacy compatibility is out of scope unless explicitly requested.
"""

from __future__ import annotations

import secrets

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

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
	"""Validate lifecycle: status, expiry, and re-scan rules."""
	if doc.status == "Revoked":
		frappe.throw(_("This scan code has been revoked."), title=_("Scan not allowed"))

	if doc.status == "Expired":
		frappe.throw(_("This scan code has expired."), title=_("Scan not allowed"))

	if doc.expires_on and get_datetime(doc.expires_on) < now_datetime():
		frappe.throw(_("This scan code has expired."), title=_("Scan not allowed"))

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
