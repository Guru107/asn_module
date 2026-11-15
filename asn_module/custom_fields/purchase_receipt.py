from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


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
				"search_index": 1,
			},
			{
				"fieldname": "asn_items",
				"fieldtype": "JSON",
				"label": "ASN Items Mapping",
				"hidden": 1,
				"insert_after": "asn",
				# Row names belong to one inserted document; a duplicate or mapper copy
				# must not carry a map that matches none of its new rows.
				"no_copy": 1,
			},
			# After the hidden mapping so it reads directly below the ASN link.
			scan_code_field("asn_items"),
		]
	}

	create_custom_fields(custom_fields)
