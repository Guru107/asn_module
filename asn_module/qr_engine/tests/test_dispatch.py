from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine import token as token_module
from asn_module.qr_engine.dispatch import (
	ActionNotFoundError,
	PermissionDeniedError,
	_resolve_action,
	dispatch,
)
from asn_module.qr_engine.token import create_token


class TestDispatch(FrappeTestCase):
	def _set_registry(
		self, action_key="create_purchase_receipt", handler_method="asn_module.tests.fake_handler"
	):
		registry = frappe.get_doc("QR Action Registry")
		registry.set("actions", [])
		registry.append(
			"actions",
			{
				"action_key": action_key,
				"handler_method": handler_method,
				"source_doctype": "DocType",
				"allowed_roles": "System Manager",
			},
		)
		registry.save(ignore_permissions=True)

	def _make_token(
		self,
		action_key="create_purchase_receipt",
		source_doctype="DocType",
		source_name="QR Action Registry",
	):
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			return create_token(action_key, source_doctype, source_name)

	def test_resolve_action_returns_registered_action(self):
		self._set_registry()

		action = _resolve_action("create_purchase_receipt")

		self.assertEqual(action["handler"], "asn_module.tests.fake_handler")
		self.assertEqual(action["source_doctype"], "DocType")
		self.assertEqual(action["allowed_roles"], ["System Manager"])

	def test_resolve_action_raises_for_unknown_action(self):
		self._set_registry()

		with self.assertRaises(ActionNotFoundError):
			_resolve_action("unknown_action")

	def test_dispatch_returns_success_payload_and_logs_success(self):
		self._set_registry(handler_method="asn_module.qr_engine.tests.test_dispatch.test_handler")
		token = self._make_token()
		frappe.local.flags.commit = False

		def test_handler(*, source_doctype, source_name, payload):
			self.assertEqual(source_doctype, "DocType")
			self.assertEqual(source_name, "QR Action Registry")
			self.assertEqual(payload["action"], "create_purchase_receipt")
			todo = frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": "Dispatch test",
				}
			).insert(ignore_permissions=True)
			return {
				"doctype": "ToDo",
				"name": todo.name,
				"url": todo.get_url(),
				"message": "Dispatch test completed",
			}

		real_get_module = frappe.get_module

		def get_module(module_path):
			if module_path == "asn_module.qr_engine.tests.test_dispatch":
				return SimpleNamespace(test_handler=test_handler)
			return real_get_module(module_path)

		with (
			patch.object(token_module, "_get_secret", return_value="test-secret"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			result = dispatch(token=token, device_info="Mobile")

		self.assertTrue(result["success"])
		self.assertEqual(result["action"], "create_purchase_receipt")
		self.assertEqual(result["doctype"], "ToDo")
		self.assertTrue(result["name"])
		self.assertTrue(result["url"])
		self.assertEqual(result["message"], "Dispatch test completed")

		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_name": "QR Action Registry",
				"result": "Success",
			},
			fields=["name", "device_info", "result_doctype", "result_name"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["device_info"], "Mobile")
		self.assertEqual(log["result_doctype"], "ToDo")
		self.assertEqual(log["result_name"], result["name"])
		self.assertTrue(frappe.local.flags.commit)

	def test_dispatch_rejects_source_doctype_mismatch_and_logs_failure(self):
		self._set_registry()
		token = self._make_token(source_doctype="Bogus DocType", source_name="Bogus Name")

		with (
			patch.object(token_module, "_get_secret", return_value="test-secret"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=frappe.get_module),
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(token=token, device_info="Desktop")

		frappe.db.rollback()
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_doctype": "DocType",
				"source_name": "QR Action Registry",
				"result": "Failure",
			},
			fields=["name", "source_doctype", "source_name", "error_message"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["source_doctype"], "DocType")
		self.assertEqual(log["source_name"], "QR Action Registry")
		self.assertIn("source doctype", log["error_message"].lower())

	def test_dispatch_rejects_partial_handler_result_and_logs_failure(self):
		self._set_registry(
			action_key="create_purchase_receipt_partial_result",
			handler_method="asn_module.qr_engine.tests.test_dispatch.partial_handler",
		)
		token = self._make_token(action_key="create_purchase_receipt_partial_result")

		def partial_handler(*, source_doctype, source_name, payload):
			return {
				"doctype": "ToDo",
				"name": "TODO-001",
			}

		real_get_module = frappe.get_module

		def get_module(module_path):
			if module_path == "asn_module.qr_engine.tests.test_dispatch":
				return SimpleNamespace(partial_handler=partial_handler)
			return real_get_module(module_path)

		with (
			patch.object(token_module, "_get_secret", return_value="test-secret"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(token=token, device_info="Desktop")

		frappe.db.rollback()
		success_logs = frappe.get_all(
			"Scan Log",
			filters={"action": "create_purchase_receipt_partial_result", "result": "Success"},
			pluck="name",
		)
		self.assertFalse(success_logs)

		failure_logs = frappe.get_all(
			"Scan Log",
			filters={"action": "create_purchase_receipt_partial_result", "result": "Failure"},
			fields=["error_message"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(failure_logs)
		self.assertIn("handler result", failure_logs[0]["error_message"].lower())

	def test_dispatch_logs_failure_when_handler_raises(self):
		self._set_registry(
			action_key="create_purchase_receipt_failure",
			handler_method="asn_module.qr_engine.tests.test_dispatch.failing_handler",
		)
		token = self._make_token(action_key="create_purchase_receipt_failure")

		def failing_handler(*, source_doctype, source_name, payload):
			raise ValueError("handler failed")

		real_get_module = frappe.get_module

		def get_module(module_path):
			if module_path == "asn_module.qr_engine.tests.test_dispatch":
				return SimpleNamespace(failing_handler=failing_handler)
			return real_get_module(module_path)

		with (
			patch.object(token_module, "_get_secret", return_value="test-secret"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			with self.assertRaises(ValueError):
				dispatch(token=token, device_info="Desktop")

		frappe.db.rollback()
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt_failure",
				"source_name": "QR Action Registry",
				"result": "Failure",
			},
			fields=["name", "device_info", "error_message"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["device_info"], "Desktop")
		self.assertIn("handler failed", log["error_message"])

	def test_dispatch_raises_permission_denied_for_users_without_allowed_roles(self):
		self._set_registry()
		token = self._make_token()

		with (
			patch.object(token_module, "_get_secret", return_value="test-secret"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["Accounts User"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=frappe.get_module),
		):
			with self.assertRaises(PermissionDeniedError):
				dispatch(token=token)
