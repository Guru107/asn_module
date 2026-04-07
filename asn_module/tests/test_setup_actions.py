import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.setup_actions import get_canonical_actions, register_actions


class TestRegisterActions(FrappeTestCase):
	def test_register_actions_creates_all_seven(self):
		register_actions()
		reg = frappe.get_single("QR Action Registry")
		action_keys = [row.action_key for row in reg.actions]
		canonical_keys = [a["action_key"] for a in get_canonical_actions()]
		self.assertEqual(sorted(action_keys), sorted(canonical_keys))
		self.assertEqual(len(action_keys), 7)

	def test_idempotent_no_duplicates(self):
		register_actions()
		register_actions()
		reg = frappe.get_single("QR Action Registry")
		action_keys = [row.action_key for row in reg.actions]
		self.assertEqual(len(action_keys), len(set(action_keys)))

	def test_each_action_maps_to_importable_handler(self):
		from importlib import import_module

		for action in get_canonical_actions():
			parts = action["handler_method"].rsplit(".", 1)
			self.assertEqual(len(parts), 2, "Invalid handler path: " + action["handler_method"])
			mod = import_module(parts[0])
			self.assertTrue(hasattr(mod, parts[1]), "Handler not found: " + action["handler_method"])
