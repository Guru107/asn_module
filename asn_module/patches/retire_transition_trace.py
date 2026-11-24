import frappe

from asn_module.patches.utils import drop_doctype


def execute():
	"""Drop the ASN transition trace: the ASN's linked documents (Connections tab) replace it."""
	frappe.delete_doc("Report", "ASN Item Transition Trace", ignore_missing=True, force=True)
	drop_doctype("ASN Transition Log")
