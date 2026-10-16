import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.patches.retire_qr_machinery import execute


def _forget_scan_code_columns() -> None:
	frappe.client_cache.delete_value("table_columns::tabScan Code")


class TestRetireQrMachinery(FrappeTestCase):
	def test_patch_drops_the_scan_code_expiry_column(self):
		if not frappe.db.has_column("Scan Code", "expires_on"):
			frappe.db.sql_ddl("ALTER TABLE `tabScan Code` ADD COLUMN `expires_on` datetime(6) NULL")
			_forget_scan_code_columns()

		self.assertTrue(frappe.db.has_column("Scan Code", "expires_on"))
		execute()
		_forget_scan_code_columns()
		self.assertFalse(frappe.db.has_column("Scan Code", "expires_on"))
