import frappe
from frappe import _

from asn_module.handlers.utils import find_pr_row_for_qi


def create_from_quality_inspection(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft stock transfer from an accepted Quality Inspection."""
	del source_doctype, payload

	qi = frappe.get_doc("Quality Inspection", source_name)

	if qi.docstatus != 1:
		frappe.throw(
			_("Quality Inspection {0} must be submitted before creating a Stock Transfer").format(source_name)
		)

	if qi.status != "Accepted":
		frappe.throw(_("Quality Inspection {0} is not Accepted. Status: {1}").format(source_name, qi.status))

	purchase_receipt = frappe.get_doc(qi.reference_type, qi.reference_name)
	if purchase_receipt.docstatus != 1:
		frappe.throw(
			_("Purchase Receipt {0} must be submitted before creating a Stock Transfer").format(
				purchase_receipt.name
			)
		)

	source_row = find_pr_row_for_qi(qi, purchase_receipt)

	destination_warehouse = (
		frappe.db.get_value(
			"Item Default",
			{"parent": qi.item_code, "company": purchase_receipt.company},
			"default_warehouse",
		)
		or source_row.warehouse
	)

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Transfer"
	stock_entry.company = purchase_receipt.company
	stock_entry.append(
		"items",
		{
			"item_code": qi.item_code,
			"qty": qi.sample_size,
			"s_warehouse": source_row.warehouse,
			"t_warehouse": destination_warehouse,
		},
	)
	stock_entry.insert(ignore_permissions=True)

	return {
		"doctype": "Stock Entry",
		"name": stock_entry.name,
		"url": f"/app/stock-entry/{stock_entry.name}",
		"message": _("Stock Transfer {0} created from Quality Inspection {1}").format(
			stock_entry.name, source_name
		),
	}
