"""Shared fixtures for integration tests: real users and session switching.

Golden-path dispatch tests use a user with **Stock User** + **Accounts User** so
``frappe.get_roles()`` satisfies both PR and PI registry rows without patching.

Do **not** add System Manager to this user — it would bypass real permission checks.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import frappe

# Roles required together for create_purchase_receipt + create_purchase_invoice dispatch.
DEFAULT_INTEGRATION_ROLES = (
	"Stock User",
	"Stock Manager",
	"Accounts User",
	"Accounts Manager",
)

INTEGRATION_USER_EMAIL = "asn.integration.ops@asn-module.test"


def ensure_integration_user(
	email: str = INTEGRATION_USER_EMAIL,
	roles: tuple[str, ...] = DEFAULT_INTEGRATION_ROLES,
) -> str:
	"""Create or update a User with the given Frappe roles. Returns email."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "ASN Integration",
				"send_welcome_email": 0,
				"enabled": 1,
				"new_password": "integration-test-pw",
			}
		)
		user.insert(ignore_permissions=True)

	desired = set(roles)
	existing = {r.role for r in (user.roles or [])}
	if existing != desired:
		user.set("roles", [])
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	return email


@contextmanager
def integration_user_context(email: str = INTEGRATION_USER_EMAIL) -> Generator[None, None, None]:
	"""Run code as ``email``, restoring the previous session user afterward."""
	previous = frappe.session.user
	frappe.set_user(email)
	try:
		yield
	finally:
		frappe.set_user(previous)


def pin_gate_pass_mode_for_tests(cls) -> None:
	"""Run a test class with gate-pass mode off, without touching the site's setting.

	Receipt-opening scans and handlers assume the fresh-site default (off);
	configured production-clone sites run it ON. Patched rather than written, so
	dispatch's mid-test commit cannot persist it and a killed run cannot leave it.
	"""
	patcher = patch("asn_module.handlers.purchase_receipt._gate_pass_mode_on", return_value=False)
	patcher.start()
	cls.addClassCleanup(patcher.stop)
