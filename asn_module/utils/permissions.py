import frappe
from frappe import _


def get_accessible_doc(doctype: str, name: str):
	"""Fetch ``doctype``/``name`` and verify the current user may read it.

	Checks the standard DocType permission system first, then falls back to
	website (portal) permission rules — supplier portal users are typically
	granted access through the latter rather than role-based permissions.

	Returns the fetched document so callers that need it are not forced into
	a second ``frappe.get_doc`` fetch.

	Raises ``frappe.PermissionError`` when neither check grants access. This
	is a genuine "no access" refusal, not a fail-open case: an absent or
	misconfigured permission never grants read access here.
	"""
	doc = frappe.get_doc(doctype, name)
	if doc.has_permission("read") or frappe.has_website_permission(doc, "read", user=frappe.session.user):
		return doc

	frappe.throw(
		_("Not permitted to access {0} {1}").format(_(doctype), name),
		frappe.PermissionError,
	)
