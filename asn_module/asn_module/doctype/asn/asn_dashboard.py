import frappe
from frappe import _


def get_data() -> dict:
	"""Connections: the documents that follow an ASN, each linked back by its ``asn`` field."""
	transactions = [
		{"label": _("Receipt"), "items": ["Purchase Receipt", "Subcontracting Receipt"]},
		{"label": _("Billing"), "items": ["Purchase Invoice"]},
	]
	# Gate Pass is a site-specific DocType; listing it where it is absent breaks the tab.
	if frappe.db.exists("DocType", "Gate Pass"):
		transactions.insert(0, {"label": _("Gate"), "items": ["Gate Pass"]})
	return {"fieldname": "asn", "transactions": transactions}
