import frappe
from frappe import _
from frappe.model.document import Document


class BarcodeMappingRow(Document):
	def validate(self):
		self.mapping_type = (self.mapping_type or "source").strip().lower()
		self.source_selector = (self.source_selector or "").strip()
		self.target_selector = (self.target_selector or "").strip()
		self.transform = (self.transform or "").strip().lower()

		if self.mapping_type not in {"source", "constant"}:
			frappe.throw(_("Mapping Type must be source or constant"))
		if self.mapping_type == "source" and not self.source_selector:
			frappe.throw(_("Source Selector is required for source mappings"))
		if not self.target_selector:
			frappe.throw(_("Target Selector is required"))
