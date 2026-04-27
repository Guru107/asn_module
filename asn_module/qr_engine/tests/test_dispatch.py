import secrets
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.dispatch import (
	ActionNotFoundError,
	PermissionDeniedError,
	_resolve_action,
	dispatch,
)
from asn_module.qr_engine.scan_codes import (
	SCAN_CODE_ALPHABET,
	SCAN_CODE_LENGTH,
	get_or_create_scan_code,
)
from asn_module.setup_actions import register_actions


class TestDispatch(FrappeTestCase):
	@classmethod
	def _snapshot_registry_actions(cls) -> list[dict]:
		registry = frappe.get_doc("QR Action Registry")
		return [
			{
				"action_key": row.action_key,
				"handler_method": row.handler_method,
				"source_doctype": row.source_doctype,
				"allowed_roles": row.allowed_roles,
			}
			for row in (registry.actions or [])
		]

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		register_actions()
		cls._registry_snapshot = cls._snapshot_registry_actions()

	@classmethod
	def tearDownClass(cls):
		registry = frappe.get_doc("QR Action Registry")
		registry.set("actions", [])
		for row in cls._registry_snapshot:
			registry.append("actions", row)
		registry.save(ignore_permissions=True)
		super().tearDownClass()

	def _set_registry(
		self,
		action_key="create_purchase_receipt",
		handler_method="asn_module.tests.fake_handler",
		source_doctype="DocType",
	):
		registry = frappe.get_doc("QR Action Registry")
		registry.set("actions", [])
		registry.append(
			"actions",
			{
				"action_key": action_key,
				"handler_method": handler_method,
				"source_doctype": source_doctype,
				"allowed_roles": "System Manager",
			},
		)
		registry.save(ignore_permissions=True)

	def _make_scan_code(
		self,
		action_key="create_purchase_receipt",
		source_doctype="DocType",
		source_name="QR Action Registry",
	):
		return get_or_create_scan_code(action_key, source_doctype, source_name)

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

	def test_resolve_action_self_heals_registry_for_known_canonical_action(self):
		# Simulate stale singleton rows from interrupted test runs.
		self._set_registry(action_key="create_purchase_receipt")

		action = _resolve_action("create_purchase_invoice")

		self.assertEqual(
			action["handler"],
			"asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
		)
		self.assertEqual(action["source_doctype"], "Purchase Receipt")

	def test_dispatch_returns_success_payload_and_logs_success(self):
		self._set_registry(handler_method="asn_module.qr_engine.tests.test_dispatch.dispatch_success_handler")
		code = self._make_scan_code()
		frappe.local.flags.commit = False

		def dispatch_success_handler(*, source_doctype, source_name, payload):
			self.assertEqual(source_doctype, "DocType")
			self.assertEqual(source_name, "QR Action Registry")
			self.assertEqual(payload["action"], "create_purchase_receipt")
			self.assertEqual(payload["scan_code"], code)
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
				return SimpleNamespace(dispatch_success_handler=dispatch_success_handler)
			return real_get_module(module_path)

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			result = dispatch(code=code, device_info="Mobile")

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

		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")

	def test_dispatch_used_scan_code_returns_existing_created_document(self):
		self._set_registry()
		code = self._make_scan_code()
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Existing scan result",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "create_purchase_receipt",
				"source_doctype": "DocType",
				"source_name": "QR Action Registry",
				"device_info": "Original",
				"result": "Success",
				"result_doctype": "ToDo",
				"result_name": todo.name,
			}
		).insert(ignore_permissions=True)

		with patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]):
			result = dispatch(code=code, device_info="Rescan")

		self.assertTrue(result["success"])
		self.assertEqual(result["action"], "create_purchase_receipt")
		self.assertEqual(result["doctype"], "ToDo")
		self.assertEqual(result["name"], todo.name)
		self.assertEqual(result["url"], todo.get_url())
		self.assertIn("Existing", result["message"])
		self.assertEqual(frappe.db.get_value("Scan Code", code, "scan_count"), 1)
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_name": "QR Action Registry",
				"result": "Success",
			},
			fields=["device_info", "result_doctype", "result_name"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["device_info"], "Rescan")
		self.assertEqual(log["result_doctype"], "ToDo")
		self.assertEqual(log["result_name"], todo.name)

	def test_dispatch_rejects_source_doctype_mismatch_and_logs_failure(self):
		self._set_registry(source_doctype="ASN")
		code_val = "".join(secrets.choice(SCAN_CODE_ALPHABET) for _ in range(SCAN_CODE_LENGTH))

		def _cleanup_scan_code():
			if frappe.db.exists("Scan Code", code_val):
				frappe.delete_doc("Scan Code", code_val, force=True, ignore_permissions=True)

		self.addCleanup(_cleanup_scan_code)

		sc = frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": code_val,
				"action_key": "create_purchase_receipt",
				"source_doctype": "Bogus DocType",
				"source_name": "Bogus Name",
				"status": "Active",
			}
		)
		sc.insert(ignore_permissions=True, ignore_links=True)

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=frappe.get_module),
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(code=sc.name, device_info="Desktop")

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
		code = self._make_scan_code(
			action_key="create_purchase_receipt_partial_result",
			source_doctype="DocType",
			source_name="QR Action Registry",
		)

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
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(code=code, device_info="Desktop")

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
		code = self._make_scan_code(
			action_key="create_purchase_receipt_failure",
			source_doctype="DocType",
			source_name="QR Action Registry",
		)

		def failing_handler(*, source_doctype, source_name, payload):
			raise ValueError("handler failed")

		real_get_module = frappe.get_module

		def get_module(module_path):
			if module_path == "asn_module.qr_engine.tests.test_dispatch":
				return SimpleNamespace(failing_handler=failing_handler)
			return real_get_module(module_path)

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=get_module),
		):
			with self.assertRaises(ValueError):
				dispatch(code=code, device_info="Desktop")

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
		code = self._make_scan_code()

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["Accounts User"]),
			patch("asn_module.qr_engine.dispatch.frappe.get_module", side_effect=frappe.get_module),
		):
			with self.assertRaises(PermissionDeniedError):
				dispatch(code=code)

	def test_dispatch_no_duplicate_success_scan_log_when_handler_returns_scan_log(self):
		self._set_registry(
			action_key="emit_scan_log_success",
			handler_method="asn_module.qr_engine.tests.test_dispatch.scan_log_emitting_handler",
		)
		code = self._make_scan_code(
			action_key="emit_scan_log_success",
			source_doctype="DocType",
			source_name="QR Action Registry",
		)
		frappe.local.flags.commit = False

		success_filters = {
			"action": "emit_scan_log_success",
			"source_name": "QR Action Registry",
			"result": "Success",
		}
		success_logs_before = frappe.db.count("Scan Log", success_filters)

		with patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]):
			result = dispatch(code=code, device_info="Handheld-Scanner-X")

		self.assertEqual(result["doctype"], "Scan Log")
		self.assertEqual(frappe.db.count("Scan Log", success_filters), success_logs_before + 1)
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.device_info, "Handheld-Scanner-X")
		self.assertTrue(frappe.local.flags.commit)


def partial_handler(*, source_doctype, source_name, payload):
	raise NotImplementedError("patched in tests")


def failing_handler(*, source_doctype, source_name, payload):
	raise NotImplementedError("patched in tests")


def scan_log_emitting_handler(*, source_doctype, source_name, payload):
	"""Test handler: persists Scan Log using ``device_info`` from payload (dispatch-injected)."""
	device = payload.get("device_info") or "Desktop"
	log = frappe.get_doc(
		{
			"doctype": "Scan Log",
			"action": payload["action"],
			"source_doctype": source_doctype,
			"source_name": source_name,
			"result": "Success",
			"device_info": device,
		}
	).insert(ignore_permissions=True)
	return {
		"doctype": "Scan Log",
		"name": log.name,
		"url": f"/app/scan-log/{log.name}",
		"message": "emit scan log test",
	}
