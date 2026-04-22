import frappe
from frappe import _
from frappe.model.document import Document


class BarcodeMappingSet(Document):
	def autoname(self):
		mapping_set_name = (self.mapping_set_name or "").strip()
		if not mapping_set_name:
			frappe.throw(_("Mapping Set Name is required"))
		self.name = mapping_set_name

	def validate(self):
		self.mapping_set_name = (self.mapping_set_name or "").strip()
		if not self.mapping_set_name:
			frappe.throw(_("Mapping Set Name is required"))
