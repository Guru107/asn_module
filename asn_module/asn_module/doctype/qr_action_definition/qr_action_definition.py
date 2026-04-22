import frappe
from frappe import _
from frappe.model.document import Document


class QRActionDefinition(Document):
	def validate(self):
		self.action_key = (self.action_key or "").strip()
		if not self.action_key:
			frappe.throw(_("Action Key is required"))
