import frappe
from frappe.model.document import Document
from frappe import _


def _parse_allowed_roles(allowed_roles: str | None) -> list[str]:
	return [role.strip() for role in (allowed_roles or "").split(",") if role.strip()]


class QRActionRegistry(Document):
	def validate(self):
		existing_roles = set(frappe.get_all("Role", pluck="name"))
		invalid_roles = []

		for row in self.actions or []:
			roles = _parse_allowed_roles(row.allowed_roles)
			if not roles:
				frappe.throw(_("Allowed Roles must contain at least one valid role"))

			for role in roles:
				if role not in existing_roles and role not in invalid_roles:
					invalid_roles.append(role)

		if invalid_roles:
			frappe.throw(_("Invalid allowed roles: {0}").format(", ".join(invalid_roles)))

	def get_action(self, action_key: str) -> dict | None:
		for row in self.actions or []:
			if row.action_key != action_key:
				continue

			return {
				"handler_method": row.handler_method,
				"source_doctype": row.source_doctype,
				"allowed_roles": _parse_allowed_roles(row.allowed_roles),
			}

		return None
