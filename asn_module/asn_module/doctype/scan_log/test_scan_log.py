import frappe
from frappe.tests.utils import FrappeTestCase


class TestScanLog(FrappeTestCase):
	def test_insert_uses_scan_prefix(self):
		log = frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "create_purchase_receipt",
				"source_doctype": "User",
				"source_name": "Administrator",
				"result": "Success",
			}
		).insert(ignore_permissions=True)

		self.assertIsNotNone(log.scan_timestamp)
		self.assertEqual(log.user, frappe.session.user)
		self.assertTrue(log.name.startswith("SCAN-"))
