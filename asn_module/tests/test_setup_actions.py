from unittest.mock import patch

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

	def test_retries_transient_registry_conflicts_and_succeeds(self):
		class DummyRegistry:
			def __init__(self, transient_error):
				self.actions = []
				self._transient_error = transient_error
				self._save_calls = 0

			def append(self, _fieldname, row):
				self.actions.append(row)

			def save(self, ignore_permissions=True):
				self._save_calls += 1
				if self._save_calls == 1:
					raise self._transient_error

		for transient_error in (
			frappe.TimestampMismatchError("stale"),
			frappe.QueryDeadlockError("deadlock"),
		):
			with self.subTest(error=type(transient_error).__name__):
				registry = DummyRegistry(transient_error)
				with (
					patch("asn_module.setup_actions.frappe.get_single", return_value=registry),
					patch("asn_module.setup_actions.frappe.db.sql", return_value=[[1]]),
					patch("asn_module.setup_actions.frappe.db.savepoint") as savepoint,
					patch("asn_module.setup_actions.frappe.db.rollback") as rollback,
					patch("asn_module.setup_actions.time.sleep"),
				):
					register_actions()

				self.assertEqual(registry._save_calls, 2)
				self.assertEqual(len(registry.actions), len(get_canonical_actions()))
				self.assertEqual(savepoint.call_count, 2)
				rollback.assert_called_once_with(save_point="register_actions_retry_0")
