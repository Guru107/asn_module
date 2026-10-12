"""Supplier invoice amount from quantity, rate, and the tax applied on the Purchase Order."""

from __future__ import annotations

import json


def _num(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def item_tax_percents(item_tax_rate) -> list[float]:
	"""Percents stored on a Purchase Order Item as ``item_tax_rate``.

	ERPNext keeps that field as JSON mapping an account head to its percent,
	for example ``{"CGST": 9, "SGST": 9}``.
	"""
	if not item_tax_rate:
		return []
	data = item_tax_rate
	if isinstance(item_tax_rate, str):
		try:
			data = json.loads(item_tax_rate)
		except json.JSONDecodeError:
			return []
	if not isinstance(data, dict):
		return []
	return [_num(value) for value in data.values()]


def header_tax_percent_from_charges(charges) -> float:
	"""Sum of Purchase Order taxes that apply as a percent of net total.

	An Actual amount is not a rate, so it is left out. Tax already included in
	the print rate is left out so it is not added twice. A Deduct row reduces
	the percent.
	"""
	total = 0.0
	for charge in charges or []:
		if _charge_value(charge, "charge_type") != "On Net Total":
			continue
		if _charge_value(charge, "included_in_print_rate"):
			continue
		rate = _num(_charge_value(charge, "rate"))
		if _charge_value(charge, "add_deduct_tax") == "Deduct":
			rate = -rate
		total += rate
	return total


def applied_tax_percent(item_tax_rate, header_tax_percent: float = 0.0) -> float:
	"""Item tax when the line has one, otherwise the Purchase Order header percent."""
	percents = item_tax_percents(item_tax_rate)
	if percents:
		return sum(percents)
	return _num(header_tax_percent)


def line_invoice_amount(qty, rate, tax_percent) -> float:
	"""``qty * rate`` plus the tax percent applied to that line."""
	return _num(qty) * _num(rate) * (1 + _num(tax_percent) / 100)


def invoice_amount_for_lines(lines) -> float:
	"""Each line is ``(qty, rate, tax_percent)``."""
	return sum(line_invoice_amount(qty, rate, tax_percent) for qty, rate, tax_percent in lines)


def _charge_value(charge, field):
	if isinstance(charge, dict):
		return charge.get(field)
	return getattr(charge, field, None)


def tax_percent_by_purchase_order_item(names: list[str]) -> dict[str, float]:
	"""Tax percent for each Purchase Order Item, from the line or its parent taxes."""
	import frappe

	wanted = [name for name in names if name]
	if not wanted:
		return {}

	fields = ["name", "parent"]
	has_item_tax = frappe.db.has_column("Purchase Order Item", "item_tax_rate")
	if has_item_tax:
		fields.append("item_tax_rate")
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"name": ["in", wanted]},
		fields=fields,
		limit_page_length=0,
	)
	header = _header_tax_percent_by_purchase_order({row.parent for row in rows if row.parent})
	percents = {}
	for row in rows:
		item_tax = getattr(row, "item_tax_rate", None) if has_item_tax else None
		percents[row.name] = applied_tax_percent(item_tax, header.get(row.parent, 0))
	return percents


def _header_tax_percent_by_purchase_order(purchase_orders: set[str]) -> dict[str, float]:
	import frappe

	if not purchase_orders or not frappe.db.table_exists("Purchase Taxes and Charges"):
		return {}

	fields = ["parent", "charge_type", "rate", "add_deduct_tax"]
	if frappe.db.has_column("Purchase Taxes and Charges", "included_in_print_rate"):
		fields.append("included_in_print_rate")
	rows = frappe.get_all(
		"Purchase Taxes and Charges",
		filters={"parent": ["in", list(purchase_orders)], "parenttype": "Purchase Order"},
		fields=fields,
		limit_page_length=0,
	)
	grouped: dict[str, list] = {}
	for row in rows:
		grouped.setdefault(row.parent, []).append(row)
	return {parent: header_tax_percent_from_charges(charges) for parent, charges in grouped.items()}
