import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document


class QRActionDefinition(Document):
	def validate(self):
		self.action_key = (self.action_key or "").strip()
		if not self.action_key:
			frappe.throw(_("Action Key is required"))

		existing_name = frappe.db.get_value(
			"QR Action Definition",
			{"action_key": self.action_key},
			"name",
		)
		if existing_name and (self.is_new() or existing_name != self.name):
			frappe.throw(_("Action Key must be unique: {0}").format(self.action_key), exc=UniqueValidationError)
