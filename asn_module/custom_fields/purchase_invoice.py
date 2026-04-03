from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create custom fields on Purchase Invoice for ASN integration."""
	custom_fields = {
		"Purchase Invoice": [
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
				"read_only": 1,
				"in_standard_filter": 1,
			},
		]
	}

	create_custom_fields(custom_fields)
