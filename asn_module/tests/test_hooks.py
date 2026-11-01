from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

import asn_module.custom_fields.purchase_invoice as purchase_invoice_fields
import asn_module.custom_fields.purchase_receipt as purchase_receipt_fields
import asn_module.custom_fields.subcontracting_receipt as subcontracting_receipt_fields
import asn_module.hooks as hooks
import asn_module.setup as setup_module


class TestHooks(FrappeTestCase):
	def test_app_include_js_registers_global_scan_assets(self):
		self.assertEqual(
			hooks.app_include_js,
			[
				"/assets/asn_module/js/scan_utils.js",
				"/assets/asn_module/js/scan_dialog.js",
				"/assets/asn_module/js/asn_module.js",
			],
		)

	def test_global_scan_asset_files_exist(self):
		public_js_dir = Path(__file__).resolve().parents[1] / "public" / "js"

		self.assertTrue((public_js_dir / "scan_utils.js").exists())
		self.assertTrue((public_js_dir / "scan_dialog.js").exists())
		self.assertTrue((public_js_dir / "asn_module.js").exists())

	@patch("asn_module.setup.setup_pi_fields")
	@patch("asn_module.setup.setup_scr_fields")
	@patch("asn_module.setup.setup_pr_fields")
	@patch("asn_module.setup.create_notifications")
	def test_after_install_sets_up_fields_and_notifications(
		self,
		create_notifications,
		setup_pr_fields,
		setup_scr_fields,
		setup_pi_fields,
	):
		call_order = []
		setup_pr_fields.side_effect = lambda: call_order.append("pr")
		setup_scr_fields.side_effect = lambda: call_order.append("scr")
		setup_pi_fields.side_effect = lambda: call_order.append("pi")
		create_notifications.side_effect = lambda: call_order.append("notif")

		setup_module.after_install()

		setup_pr_fields.assert_called_once_with()
		setup_scr_fields.assert_called_once_with()
		setup_pi_fields.assert_called_once_with()
		create_notifications.assert_called_once_with()
		self.assertEqual(call_order, ["pr", "scr", "pi", "notif"])

	def test_purchase_receipt_custom_fields_define_asn_link_and_item_mapping(self):
		with patch("asn_module.custom_fields.purchase_receipt.create_custom_fields") as create_custom_fields:
			purchase_receipt_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Purchase Receipt"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")
		self.assertEqual(fields[1]["fieldname"], "asn_items")
		self.assertEqual(fields[1]["fieldtype"], "JSON")
		# A duplicate carries new row names; the old map must not follow it.
		self.assertEqual(fields[1]["no_copy"], 1)

	def test_item_max_stock_removal_patch_is_registered_for_post_model_sync(self):
		patches = (Path(__file__).resolve().parents[1] / "patches.txt").read_text()
		post_sync = patches.split("[post_model_sync]", 1)[1]

		self.assertIn("asn_module.patches.remove_item_max_stock_field", post_sync)
		self.assertIn("asn_module.patches.retire_qr_machinery", post_sync)
		self.assertNotIn("asn_module.patches.create_item_max_stock_field", post_sync)

	def test_subcontracting_receipt_custom_fields_define_asn_link(self):
		with patch(
			"asn_module.custom_fields.subcontracting_receipt.create_custom_fields"
		) as create_custom_fields:
			subcontracting_receipt_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Subcontracting Receipt"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")

	def test_purchase_invoice_custom_fields_define_asn_link(self):
		with patch("asn_module.custom_fields.purchase_invoice.create_custom_fields") as create_custom_fields:
			purchase_invoice_fields.setup()

		fields = create_custom_fields.call_args.args[0]["Purchase Invoice"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")

	def test_global_on_trash_purges_scan_registry_for_draft_and_cancelled_documents(self):
		wildcard = hooks.doc_events.get("*")
		self.assertIsNotNone(wildcard)
		self.assertEqual(
			wildcard["on_trash"],
			"asn_module.qr_engine.scan_codes.purge_scan_registry_on_trash",
		)

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

		self.assertIn("on_cancel", pr_events)
		self.assertEqual(
			pr_events["on_cancel"],
			"asn_module.handlers.purchase_receipt.on_purchase_receipt_cancel",
		)

		self.assertIn("on_trash", pr_events)
		self.assertEqual(
			pr_events["on_trash"],
			"asn_module.handlers.purchase_receipt.on_purchase_receipt_trash",
		)
