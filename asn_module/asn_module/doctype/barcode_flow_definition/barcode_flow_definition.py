import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document


class BarcodeFlowDefinition(Document):
	def validate(self):
		self._validate_transition_keys_unique_within_flow()

	def _validate_transition_keys_unique_within_flow(self):
		seen_keys: set[str] = set()
		duplicate_keys: set[str] = set()

		for row in self.transitions or []:
			transition_key = (row.transition_key or "").strip()
			if not transition_key:
				continue

			if transition_key in seen_keys:
				duplicate_keys.add(transition_key)
				continue

			seen_keys.add(transition_key)

		if duplicate_keys:
			frappe.throw(
				_("Transition Key must be unique within this flow. Duplicate keys: {0}").format(
					", ".join(sorted(duplicate_keys))
				),
				exc=UniqueValidationError,
			)
