# Copyright (c) 2026, Gurudatt Kulkarni and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime


def execute(filters=None):
	filters = filters or {}

	flt: list = []
	if filters.get("asn"):
		flt.append(["asn", "=", filters["asn"]])
	if filters.get("item_code"):
		flt.append(["item_code", "=", filters["item_code"]])
	if filters.get("state"):
		flt.append(["state", "=", filters["state"]])
	if filters.get("transition_status"):
		flt.append(["transition_status", "=", filters["transition_status"]])
	if filters.get("ref_doctype"):
		flt.append(["ref_doctype", "=", filters["ref_doctype"]])
	if filters.get("ref_name"):
		flt.append(["ref_name", "=", filters["ref_name"]])
	if filters.get("from_date"):
		flt.append(["event_ts", ">=", get_datetime(filters["from_date"])])
	if filters.get("to_date"):
		flt.append(["event_ts", "<=", get_datetime(filters["to_date"])])
	if filters.get("failures_only"):
		flt.append(["transition_status", "=", "Error"])

	or_filters = []
	search = (filters.get("search") or "").strip()
	if search:
		pat = f"%{search}%"
		or_filters = [
			["state", "like", pat],
			["item_code", "like", pat],
			["ref_name", "like", pat],
			["details", "like", pat],
		]

	limit = int(filters.get("limit_page_length") or 200)
	limit = max(1, min(limit, 500))
	offset = int(filters.get("limit_start") or 0)
	offset = max(0, offset)

	columns = [
		_("Event Time"),
		_("ASN"),
		_("ASN Item"),
		_("Item Code"),
		_("State"),
		_("Status"),
		_("Reference"),
		_("Actor"),
		_("Error Code"),
		_("Details"),
	]

	kwargs: dict = {
		"fields": [
			"event_ts",
			"asn",
			"asn_item",
			"item_code",
			"state",
			"transition_status",
			"ref_doctype",
			"ref_name",
			"actor",
			"error_code",
			"details",
		],
		"order_by": "event_ts desc",
		"limit_start": offset,
		"limit_page_length": limit,
	}
	if flt:
		kwargs["filters"] = flt
	if or_filters:
		kwargs["or_filters"] = or_filters

	records = frappe.get_all("ASN Transition Log", **kwargs)

	rows = []
	for r in records:
		ref_parts = [r.get("ref_doctype") or "", r.get("ref_name") or ""]
		ref_display = " ".join(p for p in ref_parts if p).strip()
		rows.append(
			[
				r.get("event_ts"),
				r.get("asn"),
				r.get("asn_item"),
				r.get("item_code"),
				r.get("state"),
				r.get("transition_status"),
				ref_display,
				r.get("actor"),
				r.get("error_code") or "",
				r.get("details") or "",
			]
		)

	return columns, rows
