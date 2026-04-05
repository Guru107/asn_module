"""ASN item-level transition logging (immutable audit rows)."""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now_datetime


def _idempotency_key(
	asn: str,
	asn_item: str | None,
	state: str,
	ref_doctype: str | None,
	ref_name: str | None,
) -> str:
	raw = "|".join(
		[
			asn or "",
			asn_item or "",
			state or "",
			ref_doctype or "",
			ref_name or "",
		]
	)
	return hashlib.sha256(raw.encode()).hexdigest()


def emit_asn_item_transition(
	*,
	asn: str,
	asn_item: str | None = None,
	item_code: str | None = None,
	state: str,
	transition_status: str = "OK",
	ref_doctype: str | None = None,
	ref_name: str | None = None,
	actor: str | None = None,
	error_code: str | None = None,
	details: str | None = None,
) -> str | None:
	"""Insert one immutable transition row unless idempotency key already exists.

	Returns new document name or ``None`` if deduplicated.
	"""
	if not asn:
		return None

	key = _idempotency_key(asn, asn_item, state, ref_doctype, ref_name)
	if frappe.db.exists("ASN Transition Log", {"idempotency_key": key}):
		return None

	doc = frappe.get_doc(
		{
			"doctype": "ASN Transition Log",
			"asn": asn,
			"asn_item": asn_item,
			"item_code": item_code,
			"state": state,
			"transition_status": transition_status,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"event_ts": now_datetime(),
			"actor": actor or frappe.session.user,
			"error_code": error_code,
			"details": details,
			"idempotency_key": key,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def get_latest_transition_rows_for_asn(asn: str, limit: int = 200) -> list[dict]:
	"""Return latest transition row per ASN Item (and one doc-level fallback row if any)."""
	if not asn:
		return []

	rows = frappe.get_all(
		"ASN Transition Log",
		filters={"asn": asn},
		fields=[
			"name",
			"asn_item",
			"item_code",
			"state",
			"transition_status",
			"ref_doctype",
			"ref_name",
			"event_ts",
			"actor",
			"error_code",
		],
		order_by="event_ts desc",
		limit_page_length=limit,
	)

	seen_items: set[str] = set()
	out: list[dict] = []
	for row in rows:
		key = row.asn_item or "__document__"
		if key in seen_items:
			continue
		seen_items.add(key)
		out.append(row)
	return out
