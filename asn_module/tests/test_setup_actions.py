from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.setup_actions import (
	DEFAULT_QR_ACTION_DEFINITIONS,
	get_canonical_actions,
	register_actions,
	sync_qr_action_definitions,
)


class TestRegisterActions(FrappeTestCase):
	def seed_qr_action_definition_rows(self):
		frappe.db.delete("QR Action Definition")
		rows = [
			{
				"action_key": "create_purchase_receipt",
				"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
				"source_doctype": "ASN",
				"allowed_roles": "Stock User,Stock Manager",
				"is_active": 1,
			},
			{
				"action_key": "create_purchase_invoice",
				"handler_method": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
				"source_doctype": "Purchase Receipt",
				"allowed_roles": "Accounts User,Accounts Manager",
				"is_active": 1,
			},
			{
				"action_key": "inactive_action",
				"handler_method": "asn_module.handlers.putaway.confirm_putaway",
				"source_doctype": "Purchase Receipt",
				"allowed_roles": "Stock User,Stock Manager",
				"is_active": 0,
			},
		]
		for row in rows:
			frappe.get_doc({"doctype": "QR Action Definition", **row}).insert(ignore_permissions=True)
		return rows

	def test_register_actions_creates_all_seven(self):
		register_actions()
		reg = frappe.get_single("QR Action Registry")
		action_keys = [row.action_key for row in reg.actions]
		canonical_keys = [a["action_key"] for a in get_canonical_actions()]
		self.assertEqual(sorted(action_keys), sorted(canonical_keys))
		self.assertEqual(len(action_keys), 7)

	def test_register_actions_syncs_registry_from_qr_action_definition(self):
		rows = self.seed_qr_action_definition_rows()
		registry = frappe.get_single("QR Action Registry")
		registry.actions = []
		registry.append(
			"actions",
			{
				"action_key": "stale_action",
				"handler_method": "asn_module.handlers.putaway.confirm_putaway",
				"source_doctype": "Purchase Receipt",
				"allowed_roles": "Stock User",
			},
		)
		registry.save(ignore_permissions=True)

		register_actions()

		registry = frappe.get_single("QR Action Registry")
		expected_rows = {
			row["action_key"]: {
				"handler_method": row["handler_method"],
				"source_doctype": row["source_doctype"],
				"allowed_roles": ",".join(row["roles"]),
			}
			for row in DEFAULT_QR_ACTION_DEFINITIONS
		}
		expected_rows.update(
			{
				row["action_key"]: {
					"handler_method": row["handler_method"],
					"source_doctype": row["source_doctype"],
					"allowed_roles": row["allowed_roles"],
				}
				for row in rows
				if row["is_active"]
			}
		)
		self.assertEqual(sorted(row.action_key for row in registry.actions), sorted(expected_rows))
		for row in registry.actions:
			self.assertEqual(row.handler_method, expected_rows[row.action_key]["handler_method"])
			self.assertEqual(row.source_doctype, expected_rows[row.action_key]["source_doctype"])
			self.assertEqual(row.allowed_roles, expected_rows[row.action_key]["allowed_roles"])

	def test_sync_qr_action_definitions_adds_missing_defaults_without_overwriting_existing_rows(self):
		frappe.db.delete("QR Action Definition")
		existing_action_key = DEFAULT_QR_ACTION_DEFINITIONS[0]["action_key"]
		frappe.get_doc(
			{
				"doctype": "QR Action Definition",
				"action_key": existing_action_key,
				"handler_method": "custom.handler",
				"source_doctype": DEFAULT_QR_ACTION_DEFINITIONS[0]["source_doctype"],
				"allowed_roles": "Stock User",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

		sync_qr_action_definitions()

		self.assertEqual(
			frappe.db.count("QR Action Definition"),
			len(DEFAULT_QR_ACTION_DEFINITIONS),
		)
		existing_name = frappe.db.get_value(
			"QR Action Definition",
			{"action_key": existing_action_key},
			"name",
		)
		self.assertTrue(existing_name)
		existing = frappe.get_doc("QR Action Definition", existing_name)
		self.assertEqual(existing.handler_method, "custom.handler")
		self.assertEqual(existing.allowed_roles, "Stock User")

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
				action_rows = [
					frappe._dict(
						{
							"action_key": action["action_key"],
							"handler_method": action["handler_method"],
							"source_doctype": action["source_doctype"],
							"allowed_roles": ",".join(action["roles"]),
						}
					)
					for action in get_canonical_actions()
				]
				registry = DummyRegistry(transient_error)
				with (
					patch("asn_module.setup_actions.frappe.get_single", return_value=registry),
					patch("asn_module.setup_actions.frappe.get_all", return_value=action_rows),
					patch("asn_module.setup_actions.frappe.db.sql", return_value=[[1]]),
					patch("asn_module.setup_actions.frappe.db.savepoint") as savepoint,
					patch("asn_module.setup_actions.frappe.db.rollback") as rollback,
					patch("asn_module.setup_actions.sync_qr_action_definitions"),
					patch("asn_module.setup_actions.time.sleep"),
				):
					register_actions()

				self.assertEqual(registry._save_calls, 2)
				self.assertEqual(len(registry.actions), len(action_rows))
				self.assertEqual(savepoint.call_count, 2)
				rollback.assert_called_once_with(save_point="register_actions_retry_0")
