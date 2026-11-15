import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.asn_module.report.asn_item_rate_difference.asn_item_rate_difference import execute
from asn_module.tests.integration.fixtures import ensure_integration_user
from asn_module.utils.test_setup import before_tests


class TestRateDifferenceReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.items[0].rate = asn.items[0].rate + 10
		asn.insert(ignore_permissions=True)
		cls._asn_name = asn.name
		cls._user = ensure_integration_user("accounts-user@example.com", ("Accounts User",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_accounts_user_can_run_report(self):
		frappe.set_user(self._user)

		_columns, rows = execute({"asn": self._asn_name})

		self.assertEqual([row["asn"] for row in rows], [self._asn_name])
		self.assertEqual(rows[0]["rate_difference"], 10.0)

	def test_requires_a_scope_filter(self):
		with self.assertRaises(frappe.ValidationError):
			execute({})

	def test_date_range_outside_asn_date_returns_nothing(self):
		future = frappe.utils.add_days(frappe.utils.today(), 30)

		_columns, rows = execute({"asn": self._asn_name, "from_date": future})

		self.assertEqual(rows, [])

	def test_user_permission_on_supplier_hides_other_suppliers(self):
		supplier = frappe.db.get_value("ASN", self._asn_name, "supplier")
		other = frappe.get_doc({"doctype": "Supplier", "supplier_name": "Rate Diff Other Supplier"}).insert(
			ignore_permissions=True
		)
		frappe.get_doc(
			{"doctype": "User Permission", "user": self._user, "allow": "Supplier", "for_value": other.name}
		).insert(ignore_permissions=True)
		self.assertNotEqual(supplier, other.name)

		frappe.set_user(self._user)
		_columns, rows = execute({"asn": self._asn_name})

		self.assertEqual(rows, [])
