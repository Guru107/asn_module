import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from asn_module.stock_cap.models import CapContext, Line

EXCLUDED_ASN_STATUSES = ("Received", "Closed")


def fetch_cap_context(lines: list[Line], exclude_asn_name: str | None = None) -> CapContext:
	"""Run every read the evaluator needs and return plain data. Makes no decisions."""
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
		max_stock=_fetch_max_stock(item_codes),
		on_hand=_fetch_on_hand(item_codes, all_warehouses, branch_by_warehouse),
		in_transit=_fetch_in_transit(item_codes, all_warehouses, branch_by_warehouse, exclude_asn_name),
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


def _fetch_max_stock(item_codes: list[str]) -> dict[str, float]:
	if not frappe.db.has_column("Item", "custom_max_stock"):
		return {}

	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", "custom_max_stock"],
		limit_page_length=0,
	)
	return {row.name: flt(row.custom_max_stock) for row in rows}


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
	exclude_asn_name: str | None,
) -> dict[tuple[str, str], float]:
	"""Undelivered quantity on other submitted ASNs, converted to stock UOM.

	Raw SQL rather than the query builder because GREATEST() has no portable
	query-builder equivalent, and clamping per row matters: an over-receipted line
	must not lend negative in-transit quantity to its siblings.
	"""
	item_placeholders = ", ".join(["%s"] * len(item_codes))
	warehouse_placeholders = ", ".join(["%s"] * len(warehouses))
	status_placeholders = ", ".join(["%s"] * len(EXCLUDED_ASN_STATUSES))

	exclude_clause = ""
	params: list = [*item_codes, *warehouses, *EXCLUDED_ASN_STATUSES]
	if exclude_asn_name:
		exclude_clause = "AND asn.name != %s"
		params.append(exclude_asn_name)

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
