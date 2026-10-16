from importlib import import_module

from frappe.tests.utils import FrappeTestCase

from asn_module.setup_actions import ACTIONS, get_action


class TestActionsMap(FrappeTestCase):
	def test_map_defines_nine_actions(self):
		self.assertEqual(len(ACTIONS), 9)

	def test_get_action_returns_handler_source_and_roles(self):
		action = get_action("create_purchase_invoice")
		self.assertEqual(
			action["handler"],
			"asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
		)
		self.assertEqual(action["source_doctype"], "Purchase Receipt")
		self.assertEqual(action["allowed_roles"], ["Accounts User", "Accounts Manager"])

	def test_get_action_returns_none_for_unknown_key(self):
		self.assertIsNone(get_action("not_an_action"))

	def test_each_action_maps_to_importable_handler(self):
		for action_key, action in ACTIONS.items():
			module_path, method_name = action["handler"].rsplit(".", 1)
			module = import_module(module_path)
			self.assertTrue(hasattr(module, method_name), action_key)
