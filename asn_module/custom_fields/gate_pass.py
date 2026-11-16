import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from asn_module.custom_fields.scan_code import scan_code_field


def setup():
	"""Add the ASN link and read-only Scan Code to Gate Pass; Gate Pass belongs to another app.

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
	# Our own custom field is re-sent so an update (e.g. its index) reaches migrated sites.
	if not existing or existing.get("is_custom_field"):
		fields.append(
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
				# The scan's locking draft lookup filters on it; unindexed, it would lock every row.
				"search_index": 1,
			}
		)
	fields.append(scan_code_field("asn"))
	create_custom_fields({"Gate Pass": fields})
