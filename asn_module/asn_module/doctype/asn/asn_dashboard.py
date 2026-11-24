import frappe
from frappe import _


def get_data() -> dict:
	"""Connections: the documents that follow an ASN, each linked back by its ``asn`` field."""
	transactions = [
		{"label": _("Receipt"), "items": ["Purchase Receipt", "Subcontracting Receipt"]},
		{"label": _("Billing"), "items": ["Purchase Invoice"]},
	]
	# Gate Pass is site-specific and setup adds its asn field; listing it without both breaks the tab.
	if frappe.db.exists("DocType", "Gate Pass") and frappe.get_meta("Gate Pass").has_field("asn"):
		transactions.insert(0, {"label": _("Gate"), "items": ["Gate Pass"]})
	return {"fieldname": "asn", "transactions": transactions}
