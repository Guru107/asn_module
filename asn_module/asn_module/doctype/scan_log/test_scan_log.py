import frappe

from asn_module.tests.compat import IntegrationTestCase

# The test links only Administrator; walking these links pulls in ERPNext's Company test records.
IGNORE_TEST_RECORD_DEPENDENCIES = ["DocType", "Scan Code", "User"]


class TestScanLog(IntegrationTestCase):
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
