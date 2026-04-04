import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ScanCode(Document):
	def before_insert(self):
		if not self.generated_on:
			self.generated_on = now_datetime()
		if not self.generated_by:
			self.generated_by = frappe.session.user
