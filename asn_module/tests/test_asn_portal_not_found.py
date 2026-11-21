"""An /asn/<name> URL the caller may not view answers 404, never 500, and the 404 is not cached."""

from unittest.mock import patch

import frappe
from frappe.utils import set_request
from frappe.website.serve import get_response

from asn_module.asn_module.doctype.asn.test_asn import (
	_ensure_item,
	_ensure_other_supplier,
	create_purchase_order,
	make_test_asn,
)
from asn_module.tests.compat import IntegrationTestCase
from asn_module.utils.test_setup import before_tests, build_purchase_order_with_mandatory_fields

OWNER_EMAIL = "asn.portal.owner@example.com"
OTHER_EMAIL = "asn.portal.other@example.com"


def _ensure_website_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	return email


class TestAsnPortalNotFound(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		_ensure_item()

	def setUp(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Portal 404 Tax",
			qty=10,
		)
		self.asn = make_test_asn(purchase_order=po, qty=2)
		self.asn.insert(ignore_permissions=True)
		self.suppliers = {
			_ensure_website_user(OWNER_EMAIL): self.asn.supplier,
			_ensure_website_user(OTHER_EMAIL): _ensure_other_supplier(),
		}
		supplier_lookup = patch(
			"asn_module.templates.pages.asn._get_supplier_for_user",
			side_effect=lambda user: self.suppliers.get(user),
		)
		supplier_lookup.start()
		self.addCleanup(supplier_lookup.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def _status(self, path: str, user: str) -> int:
		frappe.set_user(user)
		set_request(method="GET", path=path)
		return get_response().status_code

	def test_another_suppliers_asn_is_not_found(self):
		self.assertEqual(self._status(f"/{self.asn.route}", OTHER_EMAIL), 404)
		self.assertEqual(self._status(f"/asn/{self.asn.name.upper()}", OTHER_EMAIL), 404)

	def test_an_asn_that_does_not_exist_is_not_found(self):
		self.assertEqual(self._status("/asn/asn-does-not-exist", "Guest"), 404)
		self.assertEqual(self._status("/asn/asn-does-not-exist", OTHER_EMAIL), 404)

	def test_the_owner_still_opens_the_asn_after_others_were_refused_with_caching_on(self):
		path = f"/{self.asn.route}"
		with patch.dict(frappe.flags, {"force_website_cache": True}):
			self.assertEqual(self._status(path, OTHER_EMAIL), 404)
			self.assertEqual(self._status(path, "Guest"), 404)
			self.assertEqual(self._status(path, OWNER_EMAIL), 200)
