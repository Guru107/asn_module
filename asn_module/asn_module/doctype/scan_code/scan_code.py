import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ScanCode(Document):
	def before_insert(self):
		if not self.generated_on:
			self.generated_on = now_datetime()
		if not self.generated_by:
			self.generated_by = frappe.session.user


def on_doctype_update():
	"""Index backing the on-trash scan-registry lookups in scan_codes.py:
	purge_scan_codes_for_source / _document_has_scan_registry_rows filter on
	(source_doctype, source_name); the existing composite leads with action_key."""
	frappe.db.add_index("Scan Code", ["source_doctype", "source_name"])
