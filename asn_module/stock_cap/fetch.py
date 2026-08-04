import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from asn_module.stock_cap.models import CapContext, Line

EXCLUDED_ASN_STATUSES = ("Received", "Closed")


def fetch_cap_context(
	lines: list[Line],
	exclude_asn_name: str | None = None,
	po_item_receiving_qty: dict[str, float] | None = None,
) -> CapContext:
	"""Run every read the evaluator needs and return plain data. Makes no decisions.

	Two independent, composable mechanisms guard against double-counting a document's own
	goods as both in-transit and incoming, for two different callers:

	``exclude_asn_name`` drops the ASN currently being saved from its own in-transit total
	(the ASN controller path, where the document being evaluated *is* the ASN).

	``po_item_receiving_qty`` subtracts, per Purchase Order Item, the stock-UOM quantity a
	Purchase Receipt is actually receiving from that Purchase Order Item's in-transit
	total -- regardless of whether the receipt is linked back to its ASN by name (the
	Purchase Receipt path -- see breaches_for_purchase_receipt for why it cannot rely on
	``doc.asn``). It subtracts a quantity rather than dropping rows outright so a partial
	receipt, or a second ASN shipping the same Purchase Order Item, keeps its own
	still-undelivered remainder counted (see fetch.py:_fetch_in_transit). They are separate
	parameters, not one overloaded to mean two things, because a Purchase Receipt has no
	ASN name to exclude by and an ASN save has no Purchase Order Items of its own to
	receive against.
	"""
	if not lines:
		return CapContext(cap_warehouses={}, max_stock={}, on_hand={}, in_transit={})

	branches = sorted({line.branch for line in lines})
	item_codes = sorted({line.item_code for line in lines})

	cap_warehouses = _fetch_cap_warehouses(branches)
	if not cap_warehouses:
		return CapContext(cap_warehouses={}, max_stock={}, on_hand={}, in_transit={})

	branch_by_warehouse = {
		warehouse: branch for branch, warehouses in cap_warehouses.items() for warehouse in warehouses
	}
	all_warehouses = sorted(branch_by_warehouse)

	return CapContext(
		cap_warehouses=cap_warehouses,
		max_stock=_fetch_max_stock(branches, item_codes),
		on_hand=_fetch_on_hand(item_codes, all_warehouses, branch_by_warehouse),
		in_transit=_fetch_in_transit(
			item_codes,
			all_warehouses,
			branch_by_warehouse,
			exclude_asn_name=exclude_asn_name,
			po_item_receiving_qty=po_item_receiving_qty,
		),
	)


def _fetch_cap_warehouses(branches: list[str]) -> dict[str, frozenset[str]]:
	"""Enabled settings only. A branch with an empty warehouse table simply never appears.

	Matched on the ``branch`` field, not ``settings.name``. ``ASN Stock Cap Settings``
	autonames from ``branch`` (``autoname: "field:branch"``) but has no rename handling, and
	Frappe's ``rename_doc`` only updates the Link *field value* on a renamed Branch's
	dependents -- it never renames or re-derives the dependent document itself. After a
	Branch rename this document's name is stale while its ``branch`` field already points at
	the new name, so matching on ``name`` would find nothing and the fail-open rule would
	silently stop enforcing for that branch. The ``branch`` field carries a DB-level unique
	constraint (see the doctype JSON), so this join can never fan out into duplicate rows for
	one branch even on an already-renamed site. The child table join still keys off
	``settings.name`` -- that is ``parent``, the parent document's own primary key, which
	``rename_doc`` keeps in lock-step with the child rows regardless of what the ``branch``
	field says.
	"""
	settings = DocType("ASN Stock Cap Settings")
	warehouse_row = DocType("ASN Stock Cap Warehouse")

	rows = (
		frappe.qb.from_(warehouse_row)
		.inner_join(settings)
		.on(settings.name == warehouse_row.parent)
		.select(settings.branch.as_("branch"), warehouse_row.warehouse)
		.where(settings.branch.isin(branches))
		.where(settings.enabled == 1)
		.where(warehouse_row.parenttype == "ASN Stock Cap Settings")
	).run(as_dict=True)

	collected: dict[str, set[str]] = {}
	for row in rows:
		if row.warehouse:
			collected.setdefault(row.branch, set()).add(row.warehouse)

	return {branch: frozenset(warehouses) for branch, warehouses in collected.items()}


def _fetch_max_stock(branches: list[str], item_codes: list[str]) -> dict[tuple[str, str], float]:
	"""Per-branch ceilings, keyed (branch, item_code).

	Guarded on the table rather than a column: a site that has not yet migrated has no
	ASN Item Branch Cap table at all, and the fail-open rule says an unconfigured site
	simply never enforces a cap.
	"""
	if not frappe.db.table_exists("ASN Item Branch Cap"):
		return {}

	rows = frappe.get_all(
		"ASN Item Branch Cap",
		filters={"branch": ["in", branches], "item": ["in", item_codes]},
		fields=["branch", "item", "max_qty"],
		limit_page_length=0,
	)
	return {(row.branch, row.item): flt(row.max_qty) for row in rows}


def _fetch_on_hand(
	item_codes: list[str], warehouses: list[str], branch_by_warehouse: dict[str, str]
) -> dict[tuple[str, str], float]:
	bin_table = DocType("Bin")
	rows = (
		frappe.qb.from_(bin_table)
		.select(bin_table.item_code, bin_table.warehouse, Sum(bin_table.actual_qty).as_("qty"))
		.where(bin_table.item_code.isin(item_codes))
		.where(bin_table.warehouse.isin(warehouses))
		.groupby(bin_table.item_code, bin_table.warehouse)
	).run(as_dict=True)

	return _aggregate_by_branch(rows, branch_by_warehouse)


def _fetch_in_transit(
	item_codes: list[str],
	warehouses: list[str],
	branch_by_warehouse: dict[str, str],
	exclude_asn_name: str | None = None,
	po_item_receiving_qty: dict[str, float] | None = None,
) -> dict[tuple[str, str], float]:
	"""Undelivered quantity on other submitted ASNs, converted to stock UOM.

	Raw SQL rather than the query builder because GREATEST() has no portable
	query-builder equivalent, and clamping matters: an over-receipted line, or a receipt
	that receives more of a Purchase Order Item than is still outstanding, must not lend
	negative in-transit quantity to its siblings.

	``po_item_receiving_qty`` -- stock-UOM quantity a Purchase Receipt is actually
	receiving, keyed by Purchase Order Item -- is subtracted from that Purchase Order
	Item's own in-transit subtotal (summed across every ASN Item row referencing it,
	clamped at zero per row exactly as before) before rows are pooled into the
	item_code/warehouse totals the evaluator uses. The clamp-at-zero is applied at
	Purchase Order Item granularity, not at the pooled item_code/warehouse level, so an
	over-receipt of one Purchase Order Item cannot eat into a different Purchase Order
	Item's still-undelivered quantity even when both land in the same item_code and
	warehouse.
	"""
	item_placeholders = ", ".join(["%s"] * len(item_codes))
	warehouse_placeholders = ", ".join(["%s"] * len(warehouses))
	status_placeholders = ", ".join(["%s"] * len(EXCLUDED_ASN_STATUSES))

	# Sargable stand-in for COALESCE(poi.warehouse, po.set_warehouse) IN (...): wrapping a
	# column in COALESCE prevents the optimizer from using any index on either column.
	# Both Purchase Order Item.warehouse and Purchase Order.set_warehouse are nullable
	# with no non-NULL default (confirmed against the live schema -- NULL, not ''), so
	# "effective warehouse" is exactly poi.warehouse when it is set, else po.set_warehouse.
	# The two OR branches reproduce that fallback without a function on either column:
	# the first branch matches when the line has its own warehouse; the second only
	# fires when it does not, mirroring COALESCE's short-circuit exactly (a non-NULL
	# poi.warehouse that simply isn't in the list correctly matches neither branch, same
	# as the original never falling back to po.set_warehouse in that case).
	warehouse_clause = (
		f"(poi.warehouse IN ({warehouse_placeholders}) "
		f"OR (poi.warehouse IS NULL AND po.set_warehouse IN ({warehouse_placeholders})))"
	)

	exclude_clauses = []
	params: list = [*item_codes, *warehouses, *warehouses, *EXCLUDED_ASN_STATUSES]

	if exclude_asn_name:
		exclude_clauses.append("AND asn.name != %s")
		params.append(exclude_asn_name)

	exclude_clause = "\n\t\t\t".join(exclude_clauses)

	receiving_qty = {
		po_item: qty for po_item, qty in (po_item_receiving_qty or {}).items() if qty and qty > 0
	}

	# Every interpolated fragment is a generated run of %s placeholders or a static
	# clause; all values travel in `params`, never in the statement text.
	# nosemgrep: frappe-sql-format-injection
	if not receiving_qty:
		rows = frappe.db.sql(
			f"""
			SELECT
				ai.item_code AS item_code,
				COALESCE(poi.warehouse, po.set_warehouse) AS warehouse,
				SUM(
					GREATEST(ai.qty - COALESCE(ai.received_qty, 0), 0)
					* CASE WHEN COALESCE(poi.conversion_factor, 0) > 0
						THEN poi.conversion_factor ELSE 1 END
				) AS qty
			FROM `tabASN Item` ai
			INNER JOIN `tabASN` asn ON asn.name = ai.parent
			INNER JOIN `tabPurchase Order Item` poi ON poi.name = ai.purchase_order_item
			INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
			WHERE ai.item_code IN ({item_placeholders})
				AND {warehouse_clause}
				AND asn.docstatus = 1
				AND asn.status NOT IN ({status_placeholders})
				{exclude_clause}
			GROUP BY ai.item_code, COALESCE(poi.warehouse, po.set_warehouse)
			""",
			params,
			as_dict=True,
		)
		return _aggregate_by_branch(rows, branch_by_warehouse)

	po_items = sorted(receiving_qty)
	receiving_union = " UNION ALL ".join(["SELECT %s AS purchase_order_item, %s AS qty"] * len(po_items))
	receiving_params: list = []
	for po_item in po_items:
		receiving_params.extend([po_item, receiving_qty[po_item]])

	rows = frappe.db.sql(
		f"""
		SELECT item_code, warehouse, SUM(remaining) AS qty
		FROM (
			SELECT
				po_totals.item_code AS item_code,
				po_totals.warehouse AS warehouse,
				GREATEST(po_totals.in_transit_qty - COALESCE(recv.qty, 0), 0) AS remaining
			FROM (
				SELECT
					ai.purchase_order_item AS purchase_order_item,
					ai.item_code AS item_code,
					COALESCE(poi.warehouse, po.set_warehouse) AS warehouse,
					SUM(
						GREATEST(ai.qty - COALESCE(ai.received_qty, 0), 0)
						* CASE WHEN COALESCE(poi.conversion_factor, 0) > 0
							THEN poi.conversion_factor ELSE 1 END
					) AS in_transit_qty
				FROM `tabASN Item` ai
				INNER JOIN `tabASN` asn ON asn.name = ai.parent
				INNER JOIN `tabPurchase Order Item` poi ON poi.name = ai.purchase_order_item
				INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
				WHERE ai.item_code IN ({item_placeholders})
					AND {warehouse_clause}
					AND asn.docstatus = 1
					AND asn.status NOT IN ({status_placeholders})
					{exclude_clause}
				GROUP BY ai.purchase_order_item, ai.item_code, COALESCE(poi.warehouse, po.set_warehouse)
			) po_totals
			LEFT JOIN (
				{receiving_union}
			) recv ON recv.purchase_order_item = po_totals.purchase_order_item
		) remainders
		GROUP BY item_code, warehouse
		""",
		[*params, *receiving_params],
		as_dict=True,
	)

	return _aggregate_by_branch(rows, branch_by_warehouse)


def _aggregate_by_branch(rows, branch_by_warehouse: dict[str, str]) -> dict[tuple[str, str], float]:
	totals: dict[tuple[str, str], float] = {}
	for row in rows:
		branch = branch_by_warehouse.get(row["warehouse"])
		if not branch:
			continue

		key = (branch, row["item_code"])
		totals[key] = totals.get(key, 0.0) + flt(row["qty"])

	return totals
