# Copyright (c) 2026, Gurudatt Kulkarni and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import get_datetime
from pypika import Order


def execute(filters=None):
	filters = filters or {}

	Log = DocType("ASN Transition Log")

	q = (
		frappe.qb.from_(Log)
		.select(
			Log.event_ts,
			Log.asn,
			Log.asn_item,
			Log.item_code,
			Log.state,
			Log.transition_status,
			Log.ref_doctype,
			Log.ref_name,
			Log.actor,
			Log.error_code,
			Log.details,
		)
		.orderby(Log.event_ts, order=Order.desc)
	)

	if filters.get("asn"):
		q = q.where(Log.asn == filters["asn"])
	if filters.get("item_code"):
		q = q.where(Log.item_code == filters["item_code"])
	if filters.get("state"):
		q = q.where(Log.state == filters["state"])
	if filters.get("transition_status"):
		q = q.where(Log.transition_status == filters["transition_status"])
	if filters.get("ref_doctype"):
		q = q.where(Log.ref_doctype == filters["ref_doctype"])
	if filters.get("ref_name"):
		q = q.where(Log.ref_name == filters["ref_name"])
	if filters.get("from_date"):
		q = q.where(Log.event_ts >= get_datetime(filters["from_date"]))
	if filters.get("to_date"):
		q = q.where(Log.event_ts <= get_datetime(filters["to_date"]))
	if filters.get("failures_only"):
		q = q.where(Log.transition_status == "Error")

	search = (filters.get("search") or "").strip()
	if search:
		pat = f"%{search}%"
		q = q.where(
			(Log.state.like(pat))
			| (Log.item_code.like(pat))
			| (Log.ref_name.like(pat))
			| (Log.details.like(pat))
		)

	limit = int(filters.get("limit_page_length") or 200)
	limit = max(1, min(limit, 500))
	offset = int(filters.get("limit_start") or 0)
	offset = max(0, offset)

	q = q.limit(limit).offset(offset)

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

	raw_rows = q.run(as_list=True)
	rows = []
	for row in raw_rows:
		(
			event_ts,
			asn,
			asn_item,
			item_code,
			state,
			transition_status,
			ref_doctype,
			ref_name,
			actor,
			error_code,
			details,
		) = row
		ref_display = " ".join(p for p in (ref_doctype, ref_name) if p).strip()
		rows.append(
			[
				event_ts,
				asn,
				asn_item,
				item_code,
				state,
				transition_status,
				ref_display,
				actor,
				error_code or "",
				details or "",
			]
		)

	return columns, rows
