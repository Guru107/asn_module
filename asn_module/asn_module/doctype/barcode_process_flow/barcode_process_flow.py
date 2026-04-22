import frappe
from frappe import _
from frappe.model.document import Document


class BarcodeProcessFlow(Document):
	def validate(self):
		self.flow_name = (self.flow_name or "").strip()
		if not self.flow_name:
			frappe.throw(_("Flow Name is required"))

		self._validate_step_uniqueness()

	def _validate_step_uniqueness(self):
		seen: set[tuple[str, str, str]] = set()
		duplicates: set[str] = set()
		for row in self.steps or []:
			from_doctype = (row.from_doctype or "").strip()
			to_doctype = (row.to_doctype or "").strip()
			label = (row.label or "").strip() or row.name
			if not from_doctype or not to_doctype:
				continue
			key = (from_doctype, to_doctype, (row.scan_action_key or "").strip())
			if key in seen:
				duplicates.add(label)
				continue
			seen.add(key)

		if duplicates:
			frappe.throw(
				_("Duplicate step detected for the same From/To DocType and Scan Action Key: {0}").format(
					", ".join(sorted(duplicates))
				)
			)
