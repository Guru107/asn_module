from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the read-only Scan Code to the Subcontracting Order and the Send to Subcontractor entry."""
	create_custom_fields(
		{
			"Subcontracting Order": [scan_code_field("supplier")],
			"Stock Entry": [scan_code_field("subcontracting_order")],
		}
	)
