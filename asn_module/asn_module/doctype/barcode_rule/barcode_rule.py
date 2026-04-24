import frappe
from frappe import _
from frappe.model.document import Document

_ALLOWED_SCOPES = {"header", "items_any", "items_all", "items_aggregate"}
_ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_set", "exists"}
_ALLOWED_AGG_FUNCS = {"", "exists", "count", "sum", "min", "max", "avg"}
_INVALID_AGG_EXISTS_OPS = {"exists", "is_set"}
_NUMERIC_AGG_FUNCS = {"count", "sum", "min", "max", "avg"}


class BarcodeRule(Document):
	def autoname(self):
		rule_name = (self.rule_name or "").strip()
		if not rule_name:
			frappe.throw(_("Rule Name is required"))
		self.name = rule_name

	def validate(self):
		self.rule_name = (self.rule_name or "").strip()
		self.scope = (self.scope or "header").strip()
		self.operator = (self.operator or "=").strip()
		self.aggregate_fn = (self.aggregate_fn or "").strip().lower()
		self.field_path = (self.field_path or "").strip()

		if not self.rule_name:
			frappe.throw(_("Rule Name is required"))
		if self.scope not in _ALLOWED_SCOPES:
			frappe.throw(_("Unsupported Scope: {0}").format(self.scope))
		if self.operator not in _ALLOWED_OPERATORS:
			frappe.throw(_("Unsupported Operator: {0}").format(self.operator))
		if self.aggregate_fn not in _ALLOWED_AGG_FUNCS:
			frappe.throw(_("Unsupported Aggregate Function: {0}").format(self.aggregate_fn))
		if not self.field_path:
			frappe.throw(_("Field Path is required"))
		if self.scope == "items_aggregate" and not self.aggregate_fn:
			frappe.throw(_("Aggregate Function is required for items_aggregate scope"))
		if self.scope != "items_aggregate" and self.aggregate_fn:
			frappe.throw(_("Aggregate Function is only allowed for items_aggregate scope"))
		if (
			self.scope == "items_aggregate"
			and self.aggregate_fn in _NUMERIC_AGG_FUNCS
			and self.operator in _INVALID_AGG_EXISTS_OPS
		):
			frappe.throw(
				_(
					"Operator {0} is not supported with aggregate function {1}; use numeric comparisons."
				).format(self.operator, self.aggregate_fn)
			)
