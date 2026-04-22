import frappe
from frappe import _
from frappe.model.document import Document


class FlowStep(Document):
	def validate(self):
		self.label = (self.label or "").strip()
		self.from_doctype = (self.from_doctype or "").strip()
		self.to_doctype = (self.to_doctype or "").strip()
		self.execution_mode = (self.execution_mode or "Mapping").strip()
		self.scan_action_key = (self.scan_action_key or "").strip()
		self.generation_mode = (self.generation_mode or "hybrid").strip().lower()

		if not self.from_doctype or not self.to_doctype:
			frappe.throw(_("From DocType and To DocType are required"))

		if self.execution_mode == "Mapping" and not (self.mapping_set or "").strip():
			frappe.throw(_("Mapping Set is required when execution mode is Mapping"))

		if self.execution_mode == "Server Script" and not (self.server_script or "").strip():
			frappe.throw(_("Server Script is required when execution mode is Server Script"))

		if self.generation_mode not in {"immediate", "runtime", "hybrid"}:
			frappe.throw(_("Generation Mode must be immediate, runtime, or hybrid"))

		if not self.label:
			self.label = f"{self.from_doctype} -> {self.to_doctype}"
