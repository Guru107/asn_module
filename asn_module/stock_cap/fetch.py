import frappe
from frappe.query_builder import DocType
from frappe.utils import cint, flt

from asn_module.stock_cap.models import CapContext, Line

EXCLUDED_ASN_STATUSES = ("Received", "Closed")

# Stock-UOM undelivered qty on one ASN Item row. GREATEST clamps over-receipts at zero so
# a single line cannot lend negative in-transit to its siblings.
_LINE_QTY_SQL = """
	GREATEST(ai.qty - COALESCE(ai.received_qty, 0), 0)
	* CASE WHEN COALESCE(poi.conversion_factor, 0) > 0
		THEN poi.conversion_factor ELSE 1 END
"""


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


def _fetch_max_stock(branches: list[str], item_codes: list[str]) -> dict[tuple[str, str], int]:
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
	# A Branch or Item rename can leave two rows for one pair. The name is no longer the
	# key, and the composite index is not unique. Prefer the tighter positive ceiling so
	# the higher one cannot silently win. Zero still means uncapped, so a zero row does
	# not erase a real ceiling.
	ceilings: dict[tuple[str, str], float] = {}
	for row in rows:
		key = (row.branch, row.item)
		qty = cint(row.max_qty)
		if key not in ceilings:
			ceilings[key] = qty
			continue
		positives = [value for value in (ceilings[key], qty) if value > 0]
		ceilings[key] = min(positives) if positives else 0
	return ceilings


def _fetch_on_hand(
	item_codes: list[str], warehouses: list[str], branch_by_warehouse: dict[str, str]
) -> dict[tuple[str, str], float]:
	"""On-hand stock in Cap Warehouses, pooled to (branch, item_code).

	``tabBin`` is unique on ``(item_code, warehouse)``, so a plain ``frappe.qb`` select
	(no ``SUM`` / ``GROUP BY``) seeks that index once. Branch pooling stays in Python:
	the result set is already one row per Cap Warehouse pair — cheaper than joining a
	constant map and aggregating in SQL for such a small set.
	"""
	bin_table = DocType("Bin")
	rows = (
		frappe.qb.from_(bin_table)
		.select(bin_table.item_code, bin_table.warehouse, bin_table.actual_qty.as_("qty"))
		.where(bin_table.item_code.isin(item_codes))
		.where(bin_table.warehouse.isin(warehouses))
	).run(as_dict=True)

	totals: dict[tuple[str, str], float] = {}
	for row in rows:
		branch = branch_by_warehouse.get(row["warehouse"])
		if not branch:
			continue
		key = (branch, row["item_code"])
		totals[key] = totals.get(key, 0.0) + flt(row["qty"])
	return totals


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

	MySQL shape (see ``docs/CodingConventions.md`` MariaDB section):

	- Sargability: the COALESCE(warehouse) ``IN`` predicate is split into two ``UNION ALL``
	  legs -- ``poi.warehouse IN (...)`` and ``poi.warehouse IS NULL AND po.set_warehouse
	  IN (...)`` -- so each leg can use an index without a function on the column.
	- ASN filters live in the ``JOIN ... ON`` so they push down with the parent join.
	- Branch pooling joins a parameterized warehouse→branch map and ``GROUP BY``s in SQL
	  (in-transit result sets are larger than Bin's unique pairs).
	- All user values travel as ``%s`` params; only placeholder runs are concatenated.
	"""
	receiving_qty = {
		po_item: qty for po_item, qty in (po_item_receiving_qty or {}).items() if qty and qty > 0
	}

	line_union_sql, line_params = _in_transit_line_union(
		item_codes, warehouses, exclude_asn_name=exclude_asn_name
	)
	branch_map_sql, branch_map_params = _branch_map_union(warehouses, branch_by_warehouse)

	if not receiving_qty:
		query = (
			"""
			SELECT
				bm.branch AS branch,
				line_rows.item_code AS item_code,
				SUM(line_rows.line_qty) AS qty
			FROM (
				"""
			+ line_union_sql
			+ """
			) line_rows
			INNER JOIN (
				"""
			+ branch_map_sql
			+ """
			) bm ON bm.warehouse = line_rows.warehouse
			GROUP BY bm.branch, line_rows.item_code
			"""
		)
		rows = frappe.db.sql(query, [*line_params, *branch_map_params], as_dict=True)
		return {(row["branch"], row["item_code"]): flt(row["qty"]) for row in rows}

	po_items = sorted(receiving_qty)
	receiving_union = " UNION ALL ".join(["SELECT %s AS purchase_order_item, %s AS qty"] * len(po_items))
	receiving_params: list = []
	for po_item in po_items:
		receiving_params.extend([po_item, receiving_qty[po_item]])

	query = (
		"""
		SELECT
			bm.branch AS branch,
			remainders.item_code AS item_code,
			SUM(remainders.remaining) AS qty
		FROM (
			SELECT
				po_totals.item_code AS item_code,
				po_totals.warehouse AS warehouse,
				GREATEST(po_totals.in_transit_qty - COALESCE(recv.qty, 0), 0) AS remaining
			FROM (
				SELECT
					line_rows.purchase_order_item AS purchase_order_item,
					line_rows.item_code AS item_code,
					line_rows.warehouse AS warehouse,
					SUM(line_rows.line_qty) AS in_transit_qty
				FROM (
					"""
		+ line_union_sql
		+ """
				) line_rows
				GROUP BY line_rows.purchase_order_item, line_rows.item_code, line_rows.warehouse
			) po_totals
			LEFT JOIN (
				"""
		+ receiving_union
		+ """
			) recv ON recv.purchase_order_item = po_totals.purchase_order_item
		) remainders
		INNER JOIN (
			"""
		+ branch_map_sql
		+ """
		) bm ON bm.warehouse = remainders.warehouse
		GROUP BY bm.branch, remainders.item_code
		"""
	)
	rows = frappe.db.sql(
		query,
		[*line_params, *receiving_params, *branch_map_params],
		as_dict=True,
	)
	return {(row["branch"], row["item_code"]): flt(row["qty"]) for row in rows}


def _placeholders(count: int) -> str:
	return ", ".join(["%s"] * count)


def _branch_map_union(warehouses: list[str], branch_by_warehouse: dict[str, str]) -> tuple[str, list]:
	"""Parameterized warehouse→branch derived table for SQL-side pooling."""
	parts = ["SELECT %s AS warehouse, %s AS branch"] * len(warehouses)
	params: list = []
	for warehouse in warehouses:
		params.extend([warehouse, branch_by_warehouse[warehouse]])
	return " UNION ALL ".join(parts), params


def _in_transit_line_union(
	item_codes: list[str],
	warehouses: list[str],
	exclude_asn_name: str | None = None,
) -> tuple[str, list]:
	"""Two sargable legs for effective warehouse = COALESCE(poi.warehouse, po.set_warehouse).

	Both Purchase Order Item.warehouse and Purchase Order.set_warehouse are nullable with
	no non-NULL default (confirmed against the live schema -- NULL, not ''), so the
	effective warehouse is exactly ``poi.warehouse`` when set, else ``po.set_warehouse``.
	``UNION ALL`` of the two legs (rather than ``OR`` / ``COALESCE`` in ``WHERE``) keeps
	each predicate index-friendly.
	"""
	item_placeholders = _placeholders(len(item_codes))
	warehouse_placeholders = _placeholders(len(warehouses))
	status_placeholders = _placeholders(len(EXCLUDED_ASN_STATUSES))

	exclude_on = ""
	exclude_params: list = []
	if exclude_asn_name:
		exclude_on = "AND asn.name != %s"
		exclude_params.append(exclude_asn_name)

	joins = (
		"""
		INNER JOIN `tabASN` asn
			ON asn.name = ai.parent
			AND asn.docstatus = 1
			AND asn.status NOT IN ("""
		+ status_placeholders
		+ """)
			"""
		+ exclude_on
		+ """
		INNER JOIN `tabPurchase Order Item` poi ON poi.name = ai.purchase_order_item
		INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
		"""
	)

	# purchase_order_item is selected so the receiving-qty path can clamp per PO Item.
	leg_line_warehouse = _in_transit_leg(
		joins=joins,
		warehouse_expr="poi.warehouse",
		item_placeholders=item_placeholders,
		warehouse_filter="AND poi.warehouse IN (" + warehouse_placeholders + ")",
	)
	leg_set_warehouse = _in_transit_leg(
		joins=joins,
		warehouse_expr="po.set_warehouse",
		item_placeholders=item_placeholders,
		warehouse_filter=(
			"AND poi.warehouse IS NULL AND po.set_warehouse IN (" + warehouse_placeholders + ")"
		),
	)

	# Per leg: status list, optional exclude, item_codes, warehouses.
	leg_params = [*EXCLUDED_ASN_STATUSES, *exclude_params, *item_codes, *warehouses]
	return leg_line_warehouse + " UNION ALL " + leg_set_warehouse, [*leg_params, *leg_params]


def _in_transit_leg(
	*,
	joins: str,
	warehouse_expr: str,
	item_placeholders: str,
	warehouse_filter: str,
) -> str:
	"""One UNION leg. The item is the Purchase Order Item's code, so a mismatched ASN item code still counts."""
	return (
		"""
		SELECT
			ai.purchase_order_item AS purchase_order_item,
			poi.item_code AS item_code,
			"""
		+ warehouse_expr
		+ """ AS warehouse,
			"""
		+ _LINE_QTY_SQL
		+ """ AS line_qty
		FROM `tabASN Item` ai
		"""
		+ joins
		+ """
		WHERE poi.item_code IN ("""
		+ item_placeholders
		+ """)
			"""
		+ warehouse_filter
	)
