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


def ensure_unique_flow_key(doc: Document, *, key_fieldname: str, key_label: str) -> None:
	flow_name = normalize_key(getattr(doc, "flow", None))
	key_value = normalize_key(getattr(doc, key_fieldname, None))
	if not flow_name or not key_value:
		return

	filters = {"flow": flow_name, key_fieldname: key_value, "name": ["!=", doc.name or ""]}
	if frappe.db.exists(doc.doctype, filters):
		frappe.throw(
			_("{0} must be unique within flow {1}.").format(key_label, flow_name),
			exc=UniqueValidationError,
		)


def validate_link_belongs_to_flow(doc: Document, fieldname: str) -> None:
	linked_name = normalize_key(getattr(doc, fieldname, None))
	if not linked_name:
		return

	field = doc.meta.get_field(fieldname)
	if not field or field.fieldtype != "Link":
		return

	linked_flow = normalize_key(frappe.db.get_value(field.options, linked_name, "flow"))
	if linked_flow and linked_flow != normalize_key(getattr(doc, "flow", None)):
		frappe.throw(
			_("{0} must belong to flow {1}.").format(field.label, normalize_key(doc.flow))
		)


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
