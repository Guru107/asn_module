import frappe
from frappe import _
from frappe.model.document import Document


def _parse_allowed_roles(allowed_roles: str | None) -> list[str]:
	return [role.strip() for role in (allowed_roles or "").split(",") if role.strip()]


class QRActionDefinition(Document):
	def validate(self):
		self.action_key = (self.action_key or "").strip()
		if not self.action_key:
			frappe.throw(_("Action Key is required"))

		roles = _parse_allowed_roles(self.allowed_roles)
		if not roles:
			frappe.throw(_("Allowed Roles must contain at least one valid role"))

		existing_roles = set(frappe.get_all("Role", pluck="name"))
		invalid_roles = [role for role in roles if role not in existing_roles]
		if invalid_roles:
			frappe.throw(_("Invalid allowed roles: {0}").format(", ".join(sorted(set(invalid_roles)))))
