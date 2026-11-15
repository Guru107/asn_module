from dataclasses import replace

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
	purchase_order_item_receiving_qty,
)
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.fetch import cap_branch_by_warehouse, fetch_cap_context
from asn_module.stock_cap.models import Breach, Line


def breaches_for_asn_rows(
	rows: list[dict],
	exclude_asn_name: str | None = None,
	consumed: dict[tuple[str, str], float] | None = None,
) -> tuple[list[Breach], dict[tuple[str, str], float]]:
	"""Evaluate one ASN's (or one bulk-upload invoice group's) rows against the cap.

	Returns ``(breaches, accepted)``. ``accepted`` is evaluate()'s own record of which
	(branch, item_code) incoming quantities it actually counted -- callers that need to
	carry headroom forward across several calls (the bulk upload loop) must feed this
	dict back in as the next call's ``consumed`` rather than re-deriving it themselves, so
	the cap-warehouse / cap-is-set / positive-qty filters live in exactly one place.
	"""
	lines = _lines_on_owning_branch(collect_lines_from_asn_rows(rows))
	if not lines:
		return [], {}

	context = fetch_cap_context(lines, exclude_asn_name=exclude_asn_name)
	return evaluate(lines, context, consumed=consumed)


def breaches_for_asn_doc(doc) -> list[Breach]:
	breaches, _accepted = breaches_for_asn_rows(asn_rows_from_doc(doc), exclude_asn_name=doc.name or None)
	return breaches


def breaches_for_purchase_receipt(doc) -> list[Breach]:
	"""Subtract the quantity this receipt is receiving from each Purchase Order Item's
	in-transit total, rather than dropping that Purchase Order Item's ASN Item rows
	wholesale.

	Keyed by ``purchase_order_item``, and only for a receipt linked to an ASN. A receipt
	with no link (the standard Purchase Order -> Create -> Purchase Receipt action) may
	only take quantity no open ASN declares, so every ASN it overlaps stays in transit.

	The correction is a quantity subtraction, not a row exclusion: an ASN shipment larger
	than a partial receipt, or a second ASN shipping the same Purchase Order Item, must
	keep contributing its own still-undelivered remainder to in-transit. Only the amount
	this receipt is actually receiving -- accepted plus rejected, in stock UOM, from
	purchase_order_item_receiving_qty -- comes off, and fetch.py:_fetch_in_transit clamps
	that subtraction at zero per Purchase Order Item so an over-receipt cannot lend
	negative in-transit to a sibling. A sibling item on the same ASN that this receipt does
	not cover is untouched, since it is keyed by a different Purchase Order Item entirely.
	"""
	lines = _lines_on_owning_branch(collect_lines_from_purchase_receipt(doc))
	if not lines:
		return []

	receiving_qty = purchase_order_item_receiving_qty(doc)
	context = fetch_cap_context(lines, po_item_receiving_qty=receiving_qty)
	breaches, _accepted = evaluate(lines, context)
	return breaches


def _lines_on_owning_branch(lines: list[Line]) -> list[Line]:
	"""Place each line on the branch that lists its warehouse as a cap warehouse.

	The document branch and the Purchase Order branch can be blank, or can name a
	different branch from the one that will actually hold the stock. In-transit already
	books the warehouse to its configured branch. The submit check has to use that same
	branch, or the goods land with no ceiling and then reserve headroom afterwards.
	A warehouse that no enabled branch lists keeps the branch the line already carries,
	and the evaluator skips it.
	"""
	owners = cap_branch_by_warehouse([line.warehouse for line in lines])
	if not owners:
		return lines

	placed = []
	for line in lines:
		owner = owners.get(line.warehouse)
		if not owner or owner == line.branch:
			placed.append(line)
			continue
		placed.append(replace(line, branch=owner))
	return placed
