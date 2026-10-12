"""ASN item rates that do not match the Purchase Order line they were taken from."""

from __future__ import annotations

RATE_EPSILON = 0.0001


def _num(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def rates_differ(asn_rate, po_rate, epsilon: float = RATE_EPSILON) -> bool:
	return abs(_num(asn_rate) - _num(po_rate)) > epsilon


def build_rate_difference_rows(records) -> list[dict]:
	"""Keep lines whose ASN rate is not the Purchase Order rate.

	``rate_difference`` is ASN rate minus Purchase Order rate.
	``amount_difference`` is that gap times quantity, for settlement.
	"""
	rows = []
	for record in records or []:
		asn_rate = _num(_field(record, "asn_rate"))
		po_rate = _num(_field(record, "po_rate"))
		if not rates_differ(asn_rate, po_rate):
			continue
		qty = _num(_field(record, "qty"))
		difference = asn_rate - po_rate
		rows.append(
			{
				"asn": _field(record, "asn") or "",
				"status": _field(record, "status") or "",
				"supplier": _field(record, "supplier") or "",
				"supplier_invoice_no": _field(record, "supplier_invoice_no") or "",
				"purchase_order": _field(record, "purchase_order") or "",
				"item_code": _field(record, "item_code") or "",
				"asn_item": _field(record, "asn_item") or "",
				"asn_rate": asn_rate,
				"po_rate": po_rate,
				"rate_difference": difference,
				"qty": qty,
				"amount_difference": qty * difference,
			}
		)
	return rows


def _field(record, name):
	if isinstance(record, dict):
		return record.get(name)
	return getattr(record, name, None)
