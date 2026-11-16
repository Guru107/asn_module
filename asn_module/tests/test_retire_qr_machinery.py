import frappe

from asn_module.patches.retire_qr_machinery import execute
from asn_module.tests.compat import IntegrationTestCase


def _forget_scan_code_columns() -> None:
	# v16 caches table columns in frappe.client_cache; v15 in a redis hash.
	if client_cache := getattr(frappe, "client_cache", None):
		client_cache.delete_value("table_columns::tabScan Code")
	else:
		frappe.cache().hdel("table_columns", "tabScan Code")


class TestRetireQrMachinery(IntegrationTestCase):
	def test_patch_drops_the_scan_code_expiry_column(self):
		if not frappe.db.has_column("Scan Code", "expires_on"):
			frappe.db.sql_ddl("ALTER TABLE `tabScan Code` ADD COLUMN `expires_on` datetime(6) NULL")
			_forget_scan_code_columns()

		self.assertTrue(frappe.db.has_column("Scan Code", "expires_on"))
		execute()
		_forget_scan_code_columns()
		self.assertFalse(frappe.db.has_column("Scan Code", "expires_on"))
