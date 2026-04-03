from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

import asn_module.hooks as hooks
import asn_module.setup as setup_module


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

	@patch("asn_module.setup.setup_pi_fields")
	@patch("asn_module.setup.setup_pr_fields")
	@patch("asn_module.setup.create_notifications")
	def test_after_install_sets_up_purchase_receipt_invoice_fields_and_notifications(
		self,
		create_notifications,
		setup_pr_fields,
		setup_pi_fields,
	):
		call_order = []
		setup_pr_fields.side_effect = lambda: call_order.append("pr")
		setup_pi_fields.side_effect = lambda: call_order.append("pi")
		create_notifications.side_effect = lambda: call_order.append("notif")

		setup_module.after_install()

		setup_pr_fields.assert_called_once_with()
		setup_pi_fields.assert_called_once_with()
		create_notifications.assert_called_once_with()
		self.assertEqual(call_order, ["pr", "pi", "notif"])
