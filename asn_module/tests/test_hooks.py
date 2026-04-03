from pathlib import Path

from frappe.tests.utils import FrappeTestCase

import asn_module.hooks as hooks


class TestHooks(FrappeTestCase):
	def test_app_include_js_registers_global_scan_assets(self):
		self.assertEqual(
			hooks.app_include_js,
			[
				"/assets/asn_module/js/scan_dialog.js",
				"/assets/asn_module/js/asn_module.js",
			],
		)

	def test_global_scan_asset_files_exist(self):
		public_js_dir = Path(__file__).resolve().parents[1] / "public" / "js"

		self.assertTrue((public_js_dir / "scan_dialog.js").exists())
		self.assertTrue((public_js_dir / "asn_module.js").exists())
