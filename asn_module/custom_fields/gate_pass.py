import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the read-only Scan Code to Gate Pass; Gate Pass belongs to another app.

	Skipped where that app is not installed (CI): its tests create their own Gate Pass.
	"""
	if not frappe.db.exists("DocType", "Gate Pass"):
		return
	# Insert After must name an existing field; the ASN link is itself a custom field.
	has_asn = frappe.get_meta("Gate Pass").has_field("asn")
	create_custom_fields({"Gate Pass": [scan_code_field("asn" if has_asn else None)]})
