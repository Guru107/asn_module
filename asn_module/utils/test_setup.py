from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

import frappe

TEST_COMPANY_NAME = "_Test Company"
TEST_COMPANY_ABBR = "_TC"


def _get_erpnext_before_tests() -> Callable[[], None] | None:
	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		return None

	before_tests = getattr(erpnext_setup_utils, "before_tests", None)
	return before_tests if callable(before_tests) else None


def _bootstrap_erpnext_defaults_without_hook() -> None:
	if not frappe.db.exists("Company", None):
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
		from frappe.utils import now_datetime

		current_year = now_datetime().year
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": TEST_COMPANY_NAME,
				"timezone": "Asia/Kolkata",
				"company_abbr": TEST_COMPANY_ABBR,
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{current_year}-04-01",
				"fy_end_date": f"{current_year + 1}-03-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@asn-module.local",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		erpnext_setup_utils = None

	for fn_name in ("set_defaults_for_tests",):
		fn = getattr(erpnext_setup_utils, fn_name, None) if erpnext_setup_utils else None
		if callable(fn):
			fn()

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - test bootstrap must persist baseline fixtures


def _ensure_company_defaults() -> None:
	company = TEST_COMPANY_NAME if frappe.db.exists("Company", TEST_COMPANY_NAME) else None
	if not company:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		return

	frappe.db.set_single_value("Global Defaults", "default_company", company)
	frappe.defaults.set_user_default("company", company)


def before_tests() -> None:
	"""Ensure a deterministic ERPNext company baseline exists for ASN tests."""
	if not frappe.db.exists("Company", None) or not frappe.db.exists("Cost Center", None):
		if erpnext_before_tests := _get_erpnext_before_tests():
			erpnext_before_tests()
		else:
			_bootstrap_erpnext_defaults_without_hook()

	_ensure_company_defaults()
