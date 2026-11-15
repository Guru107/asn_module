import frappe
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Function, IfNull, Sum
from frappe.utils import cint, flt

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


def cap_branch_by_warehouse(warehouses: list[str]) -> dict[str, str]:
	"""Enabled cap branch that lists each warehouse, keyed by warehouse.

	Matched on ``ASN Stock Cap Settings.branch``, not the settings document name, for the
	same reason ``_fetch_cap_warehouses`` is: a Branch rename leaves the document name
	stale while the ``branch`` field is current. A warehouse belongs to one branch. If two
	enabled rows still name it, the name that sorts first wins so the choice does not
	depend on query order.
	"""
	names = sorted({warehouse for warehouse in warehouses if warehouse})
	if not names or not frappe.db.table_exists("ASN Stock Cap Settings"):
		return {}

	settings = DocType("ASN Stock Cap Settings")
	warehouse_row = DocType("ASN Stock Cap Warehouse")
	rows = (
		frappe.qb.from_(warehouse_row)
		.inner_join(settings)
		.on(settings.name == warehouse_row.parent)
		.select(settings.branch.as_("branch"), warehouse_row.warehouse)
		.where(warehouse_row.warehouse.isin(names))
		.where(settings.enabled == 1)
		.where(warehouse_row.parenttype == "ASN Stock Cap Settings")
	).run(as_dict=True)

	owners: dict[str, str] = {}
	for row in rows:
		if not row.warehouse or not row.branch:
			continue
		current = owners.get(row.warehouse)
		if current is None or row.branch < current:
			owners[row.warehouse] = row.branch
	return owners


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

	One query returns the undelivered stock-UOM qty per (Purchase Order Item, item_code,
	effective warehouse). Each ASN Item row is clamped at zero first, so an over-receipted
	line cannot lend negative in-transit to its siblings.

	``po_item_receiving_qty`` -- stock-UOM quantity a Purchase Receipt is actually
	receiving, keyed by Purchase Order Item -- is subtracted from that Purchase Order
	Item's subtotal and clamped at zero *per Purchase Order Item*, so an over-receipt of
	one Purchase Order Item cannot eat into a different one's quantity even when both land
	in the same item_code and warehouse. The remainders are then pooled to branch.

	The effective warehouse is ``poi.warehouse`` when set, else ``po.set_warehouse``. It is
	two ``UNION ALL`` legs rather than ``COALESCE`` in ``WHERE`` so each predicate can use
	an index (see ``docs/CodingConventions.md`` MariaDB section).
	"""
	asn_item = DocType("ASN Item")
	asn = DocType("ASN")
	po_item = DocType("Purchase Order Item")
	po = DocType("Purchase Order")

	# GREATEST clamps over-receipts at zero; a missing or non-positive factor means 1.
	conversion = Case().when(IfNull(po_item.conversion_factor, 0) > 0, po_item.conversion_factor).else_(1)
	undelivered = Function("GREATEST", asn_item.qty - IfNull(asn_item.received_qty, 0), 0) * conversion

	def leg(warehouse_field, warehouse_filter):
		query = (
			frappe.qb.from_(asn_item)
			.inner_join(asn)
			.on(asn.name == asn_item.parent)
			.inner_join(po_item)
			.on(po_item.name == asn_item.purchase_order_item)
			.inner_join(po)
			.on(po.name == po_item.parent)
			.select(
				asn_item.purchase_order_item.as_("purchase_order_item"),
				po_item.item_code.as_("item_code"),
				warehouse_field.as_("warehouse"),
				Sum(undelivered).as_("qty"),
			)
			.where(asn.docstatus == 1)
			.where(asn.status.notin(EXCLUDED_ASN_STATUSES))
			.where(po_item.item_code.isin(item_codes))
			.where(warehouse_filter)
			.groupby(asn_item.purchase_order_item, po_item.item_code, warehouse_field)
		)
		if exclude_asn_name:
			query = query.where(asn.name != exclude_asn_name)
		return query

	rows = (
		leg(po_item.warehouse, po_item.warehouse.isin(warehouses))
		.union_all(leg(po.set_warehouse, po_item.warehouse.isnull() & po.set_warehouse.isin(warehouses)))
		.run(as_dict=True)
	)

	receiving_qty = {item: qty for item, qty in (po_item_receiving_qty or {}).items() if qty and qty > 0}
	totals: dict[tuple[str, str], float] = {}
	for row in rows:
		branch = branch_by_warehouse.get(row["warehouse"])
		if not branch:
			continue
		remaining = max(flt(row["qty"]) - flt(receiving_qty.get(row["purchase_order_item"])), 0.0)
		key = (branch, row["item_code"])
		totals[key] = totals.get(key, 0.0) + remaining
	return totals
