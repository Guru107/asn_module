import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the ASN link and read-only Scan Code to Gate Pass; Gate Pass belongs to another app.

	Skipped where that app is not installed (CI): its tests create their own Gate Pass.
	"""
	if not frappe.db.exists("DocType", "Gate Pass"):
		return
	fields = []
	# A Gate Pass that already has its own asn field must not get a second one.
	if not frappe.get_meta("Gate Pass").has_field("asn"):
		fields.append(
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
			}
		)
	fields.append(scan_code_field("asn"))
	create_custom_fields({"Gate Pass": fields})
