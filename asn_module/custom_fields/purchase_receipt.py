import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create custom fields on Purchase Receipt for ASN integration."""
	custom_fields = {
		"Purchase Receipt": [
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
				"read_only": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "asn_items",
				"fieldtype": "JSON",
				"label": "ASN Items Mapping",
				"hidden": 1,
				"insert_after": "asn",
			},
		]
	}

	create_custom_fields(custom_fields)
