import frappe


def execute():
	"""Delete the retired Item.custom_max_stock custom field.

	Ceilings now live on ASN Item Branch Cap, keyed by (item, branch). Leaving the old
	field on the Item form would show a number that no longer affects anything, which is
	the failure this feature already hit once: a configured ceiling that silently did
	nothing and gave no signal why.
	"""
	name = frappe.db.get_value("Custom Field", {"dt": "Item", "fieldname": "custom_max_stock"})
	if name:
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
