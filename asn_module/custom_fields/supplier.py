from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create custom fields on Supplier for ASN 855 gating."""
	custom_fields = {
		"Supplier": [
			{
				"fieldname": "requires_855_ack",
				"fieldtype": "Check",
				"label": "Require purchase order acknowledgment before shipment notice",
				"default": 0,
			},
		]
	}

	create_custom_fields(custom_fields)
