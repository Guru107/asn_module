from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase


class TestScanStationPage(FrappeTestCase):
	def test_scan_station_page_definition_matches_plan(self):
		frappe.reload_doc("asn_module", "page", "scan_station")

		page = frappe.get_doc("Page", "scan-station")

		self.assertEqual(page.title, "Scan Station")
		self.assertEqual(page.icon, "icon-barcode")
		self.assertEqual(page.module, "ASN Module")
		self.assertEqual(page.page_name, "scan-station")
		self.assertEqual(
			sorted(role.role for role in page.roles),
			[
				"Accounts Manager",
				"Accounts User",
				"Stock Manager",
				"Stock User",
				"System Manager",
			],
		)

	def test_scan_station_assets_exist(self):
		page_dir = Path(__file__).resolve().parent

		self.assertTrue((page_dir / "scan_station.html").exists())
		self.assertTrue((page_dir / "scan_station.js").exists())
		self.assertTrue((page_dir / "scan_station.py").exists())
