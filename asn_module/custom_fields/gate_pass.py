import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the ASN link and read-only Scan Code to Gate Pass, and the ASN Item to its rows.

	Skipped where that app is not installed (CI): its tests create their own Gate Pass.
	"""
	if not frappe.db.exists("DocType", "Gate Pass"):
		return
	fields = []
	# A Gate Pass that already has its own asn field must not get a second one,
	# but it must be the Link to ASN that scanning relies on.
	existing = frappe.get_meta("Gate Pass").get_field("asn")
	if existing and (existing.fieldtype != "Link" or existing.options != "ASN"):
		frappe.throw(
			_("Gate Pass field asn must be a Link to ASN, found {0} to {1}.").format(
				existing.fieldtype, existing.options
			)
		)
	if not existing:
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
	custom_fields = {"Gate Pass": fields}
	if frappe.db.exists("DocType", "Gate Pass Item"):
		# Receipts pair each Gate Pass row with its ASN line on this, not on row position.
		custom_fields["Gate Pass Item"] = [
			{
				"fieldname": "asn_item",
				"fieldtype": "Data",
				"label": "ASN Item",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "receive_qty",
			}
		]
	create_custom_fields(custom_fields)
