import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import _ensure_item, make_test_asn
from asn_module.patches.backfill_asn_routes import execute
from asn_module.utils.test_setup import before_tests


class TestBackfillAsnRoutes(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		_ensure_item()

	def test_patch_prefixes_bare_and_empty_routes_and_is_idempotent(self):
		bare = make_test_asn().insert(ignore_permissions=True)
		empty = make_test_asn().insert(ignore_permissions=True)
		prefixed = make_test_asn().insert(ignore_permissions=True)
		frappe.db.set_value("ASN", bare.name, "route", bare.name.lower(), update_modified=False)
		frappe.db.set_value("ASN", empty.name, "route", "", update_modified=False)
		kept = frappe.db.get_value("ASN", prefixed.name, "route")

		execute()
		execute()

		self.assertEqual(frappe.db.get_value("ASN", bare.name, "route"), bare.make_route())
		self.assertEqual(frappe.db.get_value("ASN", empty.name, "route"), empty.make_route())
		self.assertEqual(frappe.db.get_value("ASN", prefixed.name, "route"), kept)
		self.assertTrue(kept.startswith("asn/"))
