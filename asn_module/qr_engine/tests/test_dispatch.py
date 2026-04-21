import secrets
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.barcode_flow.errors import AmbiguousFlowScopeError, NoMatchingFlowError
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
		frappe.reload_doc("asn_module", "doctype", "scan_log")
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
		self._set_registry()
		code = self._make_scan_code()
		frappe.local.flags.commit = False

		flow = SimpleNamespace(name="FLOW-SUCCESS")
		transition = SimpleNamespace(transition_key="scan-to-target")
		contract = {
			"doctype": "DocType",
			"name": "QR Action Registry",
			"url": "/app/doctype/qr-action-registry",
			"message": "Dispatch test completed",
		}

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-default")),
			patch("asn_module.qr_engine.dispatch._resolve_matching_transition", return_value=transition),
			patch("asn_module.qr_engine.dispatch.execute_transition_binding", return_value=contract),
		):
			result = dispatch(code=code, device_info="Mobile")

		self.assertTrue(result["success"])
		self.assertEqual(result["action"], "create_purchase_receipt")
		self.assertEqual(result["doctype"], "DocType")
		self.assertEqual(result["name"], "QR Action Registry")
		self.assertEqual(result["url"], "/app/doctype/qr-action-registry")
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
		self.assertEqual(log["result_doctype"], "DocType")
		self.assertEqual(log["result_name"], "QR Action Registry")
		self.assertTrue(frappe.local.flags.commit)

		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")

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

		with patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]):
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
		self._set_registry(action_key="create_purchase_receipt_partial_result")
		code = self._make_scan_code(
			action_key="create_purchase_receipt_partial_result",
			source_doctype="DocType",
			source_name="QR Action Registry",
		)

		flow = SimpleNamespace(name="FLOW-PARTIAL")
		transition = SimpleNamespace(transition_key="partial-transition")

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-default")),
			patch("asn_module.qr_engine.dispatch._resolve_matching_transition", return_value=transition),
			patch(
				"asn_module.qr_engine.dispatch.execute_transition_binding",
				return_value={"doctype": "DocType", "name": "QR Action Registry"},
			),
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
		self._set_registry(action_key="create_purchase_receipt_failure")
		code = self._make_scan_code(
			action_key="create_purchase_receipt_failure",
			source_doctype="DocType",
			source_name="QR Action Registry",
		)

		flow = SimpleNamespace(name="FLOW-FAIL")
		transition = SimpleNamespace(transition_key="failing-transition")

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-default")),
			patch("asn_module.qr_engine.dispatch._resolve_matching_transition", return_value=transition),
			patch(
				"asn_module.qr_engine.dispatch.execute_transition_binding",
				side_effect=ValueError("handler failed"),
			),
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

		with patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["Accounts User"]):
			with self.assertRaises(PermissionDeniedError):
				dispatch(code=code)

	def test_dispatch_no_duplicate_success_scan_log_when_handler_returns_scan_log(self):
		self._set_registry(action_key="emit_scan_log_success")
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

		flow = SimpleNamespace(name="FLOW-SCAN-LOG")
		transition = SimpleNamespace(transition_key="scan-log-transition")

		def return_scan_log_contract(**_kwargs):
			log = frappe.get_doc(
				{
					"doctype": "Scan Log",
					"action": "emit_scan_log_success",
					"source_doctype": "DocType",
					"source_name": "QR Action Registry",
					"result": "Success",
					"device_info": "Handheld-Scanner-X",
				}
			).insert(ignore_permissions=True)
			return {
				"doctype": "Scan Log",
				"name": log.name,
				"url": f"/app/scan-log/{log.name}",
				"message": "emit scan log test",
			}

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-default")),
			patch("asn_module.qr_engine.dispatch._resolve_matching_transition", return_value=transition),
			patch("asn_module.qr_engine.dispatch.execute_transition_binding", side_effect=return_scan_log_contract),
		):
			result = dispatch(code=code, device_info="Handheld-Scanner-X")

		self.assertEqual(result["doctype"], "Scan Log")
		self.assertEqual(frappe.db.count("Scan Log", success_filters), success_logs_before + 1)
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.device_info, "Handheld-Scanner-X")
		self.assertTrue(frappe.local.flags.commit)

	def test_dispatch_raises_explicit_error_when_no_matching_flow(self):
		self._set_registry()
		code = self._make_scan_code()

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch(
				"asn_module.qr_engine.dispatch.resolve_flow_with_scope",
				side_effect=NoMatchingFlowError("No active barcode flow matches context"),
			),
		):
			with self.assertRaises(NoMatchingFlowError):
				dispatch(code=code, device_info="Desktop")

	def test_dispatch_raises_explicit_error_when_transition_matching_is_ambiguous(self):
		self._set_registry()
		code = self._make_scan_code()
		flow = SimpleNamespace(name="FLOW-AMBIG")

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-ambig")),
			patch(
				"asn_module.qr_engine.dispatch._resolve_matching_transition",
				side_effect=frappe.ValidationError("Ambiguous barcode transition resolution"),
			),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				dispatch(code=code, device_info="Desktop")

		self.assertIn("Ambiguous barcode transition resolution", str(ctx.exception))

	def test_dispatch_raises_explicit_error_when_flow_resolution_is_ambiguous(self):
		self._set_registry()
		code = self._make_scan_code()

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch(
				"asn_module.qr_engine.dispatch.resolve_flow_with_scope",
				side_effect=AmbiguousFlowScopeError("Ambiguous barcode flow resolution"),
			),
		):
			with self.assertRaises(AmbiguousFlowScopeError) as ctx:
				dispatch(code=code, device_info="Desktop")

		self.assertIn("Ambiguous barcode flow resolution", str(ctx.exception))

	def test_dispatch_success_writes_flow_metadata_to_scan_log(self):
		self._set_registry()
		code = self._make_scan_code()
		flow = SimpleNamespace(name="FLOW-RECEIVE")
		transition = SimpleNamespace(transition_key="scan-to-received")

		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch.resolve_flow_with_scope", return_value=(flow, "scope-default")),
			patch("asn_module.qr_engine.dispatch._resolve_matching_transition", return_value=transition),
			patch(
				"asn_module.qr_engine.dispatch.execute_transition_binding",
				return_value={
					"doctype": "DocType",
					"name": "QR Action Registry",
					"url": "/app/doctype/qr-action-registry",
					"message": "Flow transition executed",
				},
			) as execute_transition_binding,
		):
			result = dispatch(code=code, device_info="FlowScanner")

		execute_transition_binding.assert_called_once()
		self.assertTrue(result["success"])
		log = frappe.get_all(
			"Scan Log",
			filters={"action": "create_purchase_receipt", "result": "Success"},
			fields=[
				"name",
				"barcode_flow_definition",
				"barcode_flow_transition",
				"scope_resolution_key",
			],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["barcode_flow_definition"], "FLOW-RECEIVE")
		self.assertEqual(log["barcode_flow_transition"], "scan-to-received")
		self.assertEqual(log["scope_resolution_key"], "scope-default")
