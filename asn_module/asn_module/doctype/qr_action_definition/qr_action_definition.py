import frappe
from frappe import _
from frappe.model.document import Document


def _parse_allowed_roles(allowed_roles: str | None) -> list[str]:
	return [role.strip() for role in (allowed_roles or "").split(",") if role.strip()]


class QRActionDefinition(Document):
	def autoname(self):
		action_key = (self.action_key or "").strip()
		if not action_key:
			frappe.throw(_("Action Key is required"))
		self.name = f"ACT-{action_key}"

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

	def on_trash(self):
		transition_refs = frappe.get_all("Barcode Flow Transition", filters={"action": self.name}, pluck="name")
		binding_refs = frappe.get_all("Barcode Flow Action Binding", filters={"action": self.name}, pluck="name")

		blockers = []
		if transition_refs:
			blockers.append(f"Transition.action: {', '.join(transition_refs)}")
		if binding_refs:
			blockers.append(f"ActionBinding.action: {', '.join(binding_refs)}")
		if blockers:
			frappe.throw(
				_("Cannot delete QR Action Definition {0}. Referenced by {1}").format(
					self.name, "; ".join(blockers)
				)
			)
