import frappe
from frappe.model.document import Document


class ASNStockCapWarehouse(Document):
	pass


def on_doctype_update():
	"""One warehouse belongs to one branch. Validate checks this, but two saves can both pass it."""
	frappe.db.add_unique("ASN Stock Cap Warehouse", ["warehouse"], "unique_warehouse")
