# Copyright (c) 2026, Gurudatt Kulkarni and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime


def execute(filters=None):
	filters = filters or {}

	conditions = []
	values: list = []

	if filters.get("asn"):
		conditions.append("log.asn = %s")
		values.append(filters["asn"])

	if filters.get("item_code"):
		conditions.append("log.item_code = %s")
		values.append(filters["item_code"])

	if filters.get("state"):
		conditions.append("log.state = %s")
		values.append(filters["state"])

	if filters.get("transition_status"):
		conditions.append("log.transition_status = %s")
		values.append(filters["transition_status"])

	if filters.get("ref_doctype"):
		conditions.append("log.ref_doctype = %s")
		values.append(filters["ref_doctype"])

	if filters.get("ref_name"):
		conditions.append("log.ref_name = %s")
		values.append(filters["ref_name"])

	if filters.get("from_date"):
		conditions.append("log.event_ts >= %s")
		values.append(get_datetime(filters["from_date"]))

	if filters.get("to_date"):
		conditions.append("log.event_ts <= %s")
		values.append(get_datetime(filters["to_date"]))

	if filters.get("failures_only"):
		conditions.append("log.transition_status = %s")
		values.append("Error")

	where_clause = " AND ".join(conditions) if conditions else "1=1"

	search = (filters.get("search") or "").strip()
	if search:
		where_clause += " AND (log.state LIKE %s OR log.item_code LIKE %s OR log.ref_name LIKE %s OR log.details LIKE %s)"
		like = f"%{search}%"
		values.extend([like, like, like, like])

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

	rows = frappe.db.sql(
		f"""
		SELECT
			log.event_ts,
			log.asn,
			log.asn_item,
			log.item_code,
			log.state,
			log.transition_status,
			CONCAT_WS(' ', IFNULL(log.ref_doctype, ''), IFNULL(log.ref_name, '')),
			log.actor,
			IFNULL(log.error_code, ''),
			IFNULL(log.details, '')
		FROM `tabASN Transition Log` log
		WHERE {where_clause}
		ORDER BY log.event_ts DESC
		LIMIT %s OFFSET %s
		""",
		tuple(values) + (limit, offset),
		as_list=True,
	)

	return columns, rows
