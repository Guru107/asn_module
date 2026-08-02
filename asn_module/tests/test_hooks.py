from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

import asn_module.custom_fields.item as item_fields
import asn_module.custom_fields.purchase_invoice as purchase_invoice_fields
import asn_module.custom_fields.purchase_receipt as purchase_receipt_fields
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

	@patch("asn_module.setup.setup_item_fields")
	@patch("asn_module.setup.setup_pi_fields")
	@patch("asn_module.setup.setup_pr_fields")
	@patch("asn_module.setup.create_notifications")
	@patch("asn_module.setup.register_actions")
	def test_after_install_sets_up_fields_notifications_and_actions(
		self,
		register_actions,
		create_notifications,
		setup_pr_fields,
		setup_pi_fields,
		setup_item_fields,
	):
		call_order = []
		setup_pr_fields.side_effect = lambda: call_order.append("pr")
		setup_pi_fields.side_effect = lambda: call_order.append("pi")
		setup_item_fields.side_effect = lambda: call_order.append("item")
		create_notifications.side_effect = lambda: call_order.append("notif")
		register_actions.side_effect = lambda: call_order.append("actions")

		setup_module.after_install()

		setup_pr_fields.assert_called_once_with()
		setup_pi_fields.assert_called_once_with()
		setup_item_fields.assert_called_once_with()
		create_notifications.assert_called_once_with()
		register_actions.assert_called_once_with()
		self.assertEqual(call_order, ["pr", "pi", "item", "notif", "actions"])

	def test_purchase_receipt_custom_fields_define_asn_link_and_item_mapping(self):
		with patch("asn_module.custom_fields.purchase_receipt.create_custom_fields") as create_custom_fields:
			purchase_receipt_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Purchase Receipt"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")
		self.assertEqual(fields[1]["fieldname"], "asn_items")
		self.assertEqual(fields[1]["fieldtype"], "JSON")

	def test_item_custom_fields_define_max_stock(self):
		with patch("asn_module.custom_fields.item.create_custom_fields") as create_custom_fields:
			item_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Item"]
		self.assertEqual(fields[0]["fieldname"], "custom_max_stock")
		self.assertEqual(fields[0]["fieldtype"], "Float")
		self.assertEqual(fields[0]["insert_after"], "safety_stock")
		self.assertEqual(fields[0]["non_negative"], 1)

	def test_item_max_stock_patch_is_registered_for_post_model_sync(self):
		patches = (Path(__file__).resolve().parents[1] / "patches.txt").read_text()
		post_sync = patches.split("[post_model_sync]", 1)[1]
		self.assertIn("asn_module.patches.create_item_max_stock_field", post_sync)

	def test_purchase_invoice_custom_fields_define_asn_link(self):
		with patch("asn_module.custom_fields.purchase_invoice.create_custom_fields") as create_custom_fields:
			purchase_invoice_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Purchase Invoice"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")

	def test_purchase_receipt_doc_events_registers_all_handlers(self):
		pr_events = hooks.doc_events.get("Purchase Receipt")
		self.assertIsNotNone(pr_events, "Purchase Receipt entry missing from doc_events")

		self.assertIn("before_submit", pr_events)
		self.assertEqual(
			pr_events["before_submit"],
			"asn_module.handlers.purchase_receipt.on_purchase_receipt_before_submit",
		)

		self.assertIn("on_submit", pr_events)
		self.assertEqual(
			pr_events["on_submit"],
			"asn_module.handlers.purchase_receipt.on_purchase_receipt_submit",
		)

		self.assertIn("on_trash", pr_events)
		self.assertEqual(
			pr_events["on_trash"],
			"asn_module.handlers.purchase_receipt.on_purchase_receipt_trash",
		)
