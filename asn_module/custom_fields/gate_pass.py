import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the ASN link and read-only Scan Code to Gate Pass; Gate Pass belongs to another app.

	Skipped where that app is not installed (CI): its tests create their own Gate Pass.
	"""
	if not frappe.db.exists("DocType", "Gate Pass"):
		return
	create_custom_fields(
		{
			"Gate Pass": [
				{
					"fieldname": "asn",
					"fieldtype": "Link",
					"label": "ASN",
					"options": "ASN",
					"insert_after": "supplier",
				},
				scan_code_field("asn"),
			]
		}
	)
