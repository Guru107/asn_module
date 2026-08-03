import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from asn_module.stock_cap.models import CapContext, Line

EXCLUDED_ASN_STATUSES = ("Received", "Closed")


def fetch_cap_context(
	lines: list[Line],
	exclude_asn_name: str | None = None,
	exclude_po_items: set[str] | frozenset[str] | None = None,
) -> CapContext:
	"""Run every read the evaluator needs and return plain data. Makes no decisions.

	Two independent, composable exclusion mechanisms guard against double-counting a
	document's own goods as both in-transit and incoming, for two different callers:

	``exclude_asn_name`` drops the ASN currently being saved from its own in-transit total
	(the ASN controller path, where the document being evaluated *is* the ASN).

	``exclude_po_items`` drops ASN Item rows whose Purchase Order Item a Purchase Receipt is
	consuming, regardless of whether that receipt is linked back to its ASN by name (the
	Purchase Receipt path -- see breaches_for_purchase_receipt for why it cannot rely on
	``doc.asn``). They are separate parameters, not one overloaded to mean two things,
	because a Purchase Receipt has no ASN name to exclude by and an ASN save has no
	Purchase Order Items of its own to exclude by.
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
			exclude_po_items=exclude_po_items,
		),
	)


def _fetch_cap_warehouses(branches: list[str]) -> dict[str, frozenset[str]]:
	"""Enabled settings only. A branch with an empty warehouse table simply never appears."""
	settings = DocType("ASN Stock Cap Settings")
	warehouse_row = DocType("ASN Stock Cap Warehouse")

	rows = (
		frappe.qb.from_(warehouse_row)
		.inner_join(settings)
		.on(settings.name == warehouse_row.parent)
		.select(settings.name.as_("branch"), warehouse_row.warehouse)
		.where(settings.name.isin(branches))
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
	exclude_po_items: set[str] | frozenset[str] | None = None,
) -> dict[tuple[str, str], float]:
	"""Undelivered quantity on other submitted ASNs, converted to stock UOM.

	Raw SQL rather than the query builder because GREATEST() has no portable
	query-builder equivalent, and clamping per row matters: an over-receipted line
	must not lend negative in-transit quantity to its siblings.
	"""
	item_placeholders = ", ".join(["%s"] * len(item_codes))
	warehouse_placeholders = ", ".join(["%s"] * len(warehouses))
	status_placeholders = ", ".join(["%s"] * len(EXCLUDED_ASN_STATUSES))

	exclude_clauses = []
	params: list = [*item_codes, *warehouses, *EXCLUDED_ASN_STATUSES]

	if exclude_asn_name:
		exclude_clauses.append("AND asn.name != %s")
		params.append(exclude_asn_name)

	if exclude_po_items:
		po_items = sorted(exclude_po_items)
		po_item_placeholders = ", ".join(["%s"] * len(po_items))
		exclude_clauses.append(f"AND ai.purchase_order_item NOT IN ({po_item_placeholders})")
		params.extend(po_items)

	exclude_clause = "\n\t\t\t".join(exclude_clauses)

	# Every interpolated fragment is a generated run of %s placeholders or a static
	# clause; all values travel in `params`, never in the statement text.
	# nosemgrep: frappe-sql-format-injection
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
			AND COALESCE(poi.warehouse, po.set_warehouse) IN ({warehouse_placeholders})
			AND asn.docstatus = 1
			AND asn.status NOT IN ({status_placeholders})
			{exclude_clause}
		GROUP BY ai.item_code, COALESCE(poi.warehouse, po.set_warehouse)
		""",
		params,
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
