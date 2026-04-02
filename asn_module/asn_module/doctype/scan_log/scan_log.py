import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ScanLog(Document):
	def before_insert(self):
		self.scan_timestamp = now_datetime()
		self.user = frappe.session.user
