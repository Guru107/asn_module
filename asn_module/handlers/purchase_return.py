import frappe
from frappe import _


def create_from_quality_inspection(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft purchase return from a rejected Quality Inspection."""
	del source_doctype, payload

	qi = frappe.get_doc("Quality Inspection", source_name)

	if qi.docstatus != 1:
		frappe.throw(
			_("Quality Inspection {0} must be submitted before creating a Purchase Return").format(
				source_name
			)
		)

	if qi.status != "Rejected":
		frappe.throw(_("Quality Inspection {0} is not Rejected. Status: {1}").format(source_name, qi.status))

	original_pr = frappe.get_doc(qi.reference_type, qi.reference_name)
	if original_pr.docstatus != 1:
		frappe.throw(
			_("Purchase Receipt {0} must be submitted before creating a Purchase Return").format(
				original_pr.name
			)
		)

	source_row = None
	qi_pr_item = getattr(qi, "purchase_receipt_item", None)
	if qi_pr_item:
		for item in original_pr.items:
			if item.name == qi_pr_item:
				source_row = item
				break

	if not source_row:
		matching_rows = [item for item in original_pr.items if item.item_code == qi.item_code]
		if len(matching_rows) == 1:
			source_row = matching_rows[0]
		elif len(matching_rows) > 1:
			frappe.throw(
				_(
					"Multiple Purchase Receipt rows found for item {0} in {1}. "
					"Set a specific purchase_receipt_item on Quality Inspection {2}."
				).format(qi.item_code, qi.reference_name, qi.name)
			)

	if not source_row:
		frappe.throw(_("Item {0} not found in {1}").format(qi.item_code, qi.reference_name))

	return_pr = frappe.new_doc("Purchase Receipt")
	return_pr.company = original_pr.company
	return_pr.supplier = original_pr.supplier
	return_pr.is_return = 1
	return_pr.return_against = original_pr.name
	return_pr.append(
		"items",
		{
			"item_code": qi.item_code,
			"item_name": source_row.item_name,
			"qty": -1 * qi.sample_size,
			"uom": source_row.uom,
			"rate": source_row.rate,
			"warehouse": source_row.warehouse,
			"purchase_order": source_row.purchase_order,
			"purchase_order_item": source_row.purchase_order_item,
			"purchase_receipt_item": source_row.name,
		},
	)
	return_pr.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Receipt",
		"name": return_pr.name,
		"url": f"/app/purchase-receipt/{return_pr.name}",
		"message": _("Purchase Return {0} created from Quality Inspection {1}").format(
			return_pr.name, source_name
		),
	}
