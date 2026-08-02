from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create the branch stock cap field on Item.

	The stock cap reads this field and fails open when it is absent, so a site without
	it simply never enforces a cap. That silence is why the field is created here rather
	than by hand: a forgotten field makes the whole feature inert with nothing to notice.
	"""
	custom_fields = {
		"Item": [
			{
				"fieldname": "custom_max_stock",
				"fieldtype": "Float",
				"label": "Max Stock",
				"insert_after": "safety_stock",
				"non_negative": 1,
				"description": (
					"Largest quantity of this item allowed in a branch, in stock UOM. Leave at 0 for no cap."
				),
			}
		]
	}

	create_custom_fields(custom_fields)
