import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now
from frappe.utils import now_datetime

LOG_RETENTION_DAYS = 180


class ScanLog(Document):
	def before_insert(self):
		self.scan_timestamp = now_datetime()
		self.user = frappe.session.user

	@staticmethod
	def clear_old_logs(days: int = LOG_RETENTION_DAYS) -> None:
		"""Log Settings clearing hook: drop rows older than ``days``."""
		table = frappe.qb.DocType("Scan Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))


def on_doctype_update():
	"""Indexes backing the on-trash scan-registry lookups in scan_codes.py:
	purge/reactivation filter on (result_doctype, result_name) and
	(source_doctype, source_name); existing indexes lead with other columns."""
	frappe.db.add_index("Scan Log", ["result_doctype", "result_name"])
	frappe.db.add_index("Scan Log", ["source_doctype", "source_name"])
