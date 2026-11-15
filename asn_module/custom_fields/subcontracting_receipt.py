from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


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
			{
				"fieldname": "asn_items",
				"fieldtype": "JSON",
				"label": "ASN Items Mapping",
				"hidden": 1,
				"insert_after": "asn",
				# Row names belong to one inserted document; an amend or return must not carry it.
				"no_copy": 1,
			},
			scan_code_field("asn_items"),
		]
	}

	create_custom_fields(custom_fields)
