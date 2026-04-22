import frappe
from frappe import _
from frappe.exceptions import UniqueValidationError
from frappe.model.document import Document
from frappe.utils import cint


def normalize_key(value: str | None) -> str:
	return (value or "").strip()


def build_flow_entity_name(*, flow: str | None, entity_code: str, key: str | None, key_label: str) -> str:
	flow_name = normalize_key(flow)
	key_value = normalize_key(key)
	if not flow_name:
		frappe.throw(_("Flow is required"))
	if not key_value:
		frappe.throw(_("{0} is required").format(key_label))
	return f"FLOW-{flow_name}-{entity_code}-{key_value}"


class BarcodeFlowDefinition(Document):
	def validate(self):
		self.flow_name = normalize_key(self.flow_name)
		if not self.flow_name:
			frappe.throw(_("Flow Name is required"))

		self._validate_unique_scope_keys()
		self._validate_single_default_scope()

	def _validate_unique_scope_keys(self):
		seen_keys: set[str] = set()
		duplicate_keys: set[str] = set()

		for row in self.scopes or []:
			scope_key = normalize_key(row.scope_key)
			if not scope_key:
				continue
			if scope_key in seen_keys:
				duplicate_keys.add(scope_key)
				continue
			seen_keys.add(scope_key)

		if duplicate_keys:
			frappe.throw(
				_("Scope Key must be unique within this flow. Duplicate keys: {0}").format(
					", ".join(sorted(duplicate_keys))
				),
				exc=UniqueValidationError,
			)

	def _validate_single_default_scope(self):
		default_scope_count = sum(1 for row in self.scopes or [] if cint(row.is_default))
		if default_scope_count > 1:
			frappe.throw(_("Only one scope can be marked as default."))
