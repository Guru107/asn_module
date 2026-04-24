import frappe
from frappe import _
from frappe.model.document import Document


class BarcodeMappingRow(Document):
	def validate(self):
		self.mapping_type = (self.mapping_type or "source").strip().lower()
		self.source_field = (self.source_field or "").strip()
		self.target_field = (self.target_field or "").strip()
		self.transform = (self.transform or "").strip().lower()

		if self.mapping_type not in {"source", "constant"}:
			frappe.throw(_("Mapping Type must be source or constant"))
		if self.mapping_type == "source" and not self.source_field:
			frappe.throw(_("Source Field is required for source mappings"))
		if not self.target_field:
			frappe.throw(_("Target Field is required"))
