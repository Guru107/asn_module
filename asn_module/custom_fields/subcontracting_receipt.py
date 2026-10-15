from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Link a Subcontracting Receipt back to the Job ASN that opened it."""
	custom_fields = {
		"Subcontracting Receipt": [
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
