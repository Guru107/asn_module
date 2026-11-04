import secrets
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.dispatch import (
	ActionNotFoundError,
	PermissionDeniedError,
	_latest_success_document,
	_resolve_action,
	dispatch,
)
from asn_module.qr_engine.scan_codes import (
	SCAN_CODE_ALPHABET,
	SCAN_CODE_LENGTH,
	get_or_create_scan_code,
)

SOURCE_DOCTYPE = "DocType"
SOURCE_NAME = "User"


@contextmanager
def patched_action(action_key, handler, *, source_doctype=SOURCE_DOCTYPE, roles=None):
	roles = list(roles or ["System Manager"])
	with patch.dict(
		"asn_module.setup_actions.ACTIONS",
		{
			action_key: {
				"handler": handler,
				"source_doctype": source_doctype,
				"roles": roles,
			}
		},
	):
		yield


class TestDispatch(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# dispatch commits on failure; a real commit would persist these tests' Scan
		# Codes past the class rollback. The real commit is covered by
		# TestDispatchFailureCommit below.
		patcher = patch.object(frappe.db, "commit")
		patcher.start()
		self.addCleanup(patcher.stop)

	def _make_scan_code(
		self,
		action_key="create_purchase_receipt",
		source_doctype=SOURCE_DOCTYPE,
		source_name=SOURCE_NAME,
	):
		return get_or_create_scan_code(action_key, source_doctype, source_name)

	def test_resolve_action_returns_the_code_defined_action(self):
		action = _resolve_action("create_purchase_receipt")

		self.assertEqual(action["handler"], "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn")
		self.assertEqual(action["source_doctype"], "ASN")
		self.assertEqual(action["allowed_roles"], ["Stock User", "Stock Manager"])

	def test_resolve_action_raises_for_unknown_action(self):
		with self.assertRaises(ActionNotFoundError):
			_resolve_action("unknown_action")

	def test_dispatch_returns_success_payload_and_logs_success(self):
		code = self._make_scan_code()
		frappe.local.flags.commit = False

		def call_handler(handler_method, source_doctype, source_name, payload):
			self.assertEqual(handler_method, "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn")
			self.assertEqual(source_doctype, SOURCE_DOCTYPE)
			self.assertEqual(source_name, SOURCE_NAME)
			self.assertEqual(payload["action"], "create_purchase_receipt")
			self.assertEqual(payload["scan_code"], code)
			todo = frappe.get_doc({"doctype": "ToDo", "description": "Dispatch test"}).insert(
				ignore_permissions=True
			)
			return {
				"doctype": "ToDo",
				"name": todo.name,
				"url": todo.get_url(),
				"message": "Dispatch test completed",
			}

		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=call_handler),
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
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": code,
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
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": code,
				"device_info": "Original",
				"result": "Success",
				"result_doctype": "ToDo",
				"result_name": todo.name,
			}
		).insert(ignore_permissions=True)

		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
		):
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
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": code,
				"result": "Success",
			},
			fields=["device_info", "result_doctype", "result_name"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["device_info"], "Rescan")
		self.assertEqual(log["result_doctype"], "ToDo")
		self.assertEqual(log["result_name"], todo.name)

	def test_existing_success_result_logs_and_raises_unexpected_errors(self):
		unexpected_error = RuntimeError("database unavailable")

		with (
			patch(
				"asn_module.qr_engine.dispatch.frappe.get_all",
				return_value=[{"result_doctype": "ToDo", "result_name": "TODO-0001"}],
			),
			patch("asn_module.qr_engine.dispatch.frappe.db.exists", return_value=True),
			patch("asn_module.qr_engine.dispatch.frappe.get_doc", side_effect=unexpected_error),
			patch("asn_module.qr_engine.dispatch.frappe.log_error") as log_error,
			self.assertRaises(RuntimeError),
		):
			_latest_success_document(
				"create_purchase_receipt",
				SOURCE_DOCTYPE,
				SOURCE_NAME,
				"SCAN-CODE-1",
			)

		log_error.assert_called_once()

	def test_dispatch_used_scan_code_does_not_reopen_other_barcode_result(self):
		other_code = self._make_scan_code()
		frappe.db.set_value("Scan Code", other_code, "status", "Used", update_modified=False)
		current_code = get_or_create_scan_code("create_purchase_receipt", SOURCE_DOCTYPE, SOURCE_NAME)
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Other barcode result",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Scan Code", current_code, "status", "Used", update_modified=False)
		frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "create_purchase_receipt",
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": other_code,
				"device_info": "Original",
				"result": "Success",
				"result_doctype": "ToDo",
				"result_name": todo.name,
			}
		).insert(ignore_permissions=True)

		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			self.assertRaises(frappe.ValidationError),
		):
			dispatch(code=current_code, device_info="Rescan")

		self.assertEqual(frappe.db.get_value("Scan Code", current_code, "scan_count"), 0)

	def test_dispatch_used_scan_code_rejects_when_prior_result_is_missing(self):
		code = self._make_scan_code()
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "create_purchase_receipt",
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": code,
				"device_info": "Original",
				"result": "Success",
				"result_doctype": "ToDo",
				"result_name": "MISSING-TODO-0001",
			}
		).insert(ignore_permissions=True, ignore_links=True)

		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			self.assertRaises(frappe.ValidationError),
		):
			dispatch(code=code, device_info="Rescan")

		self.assertEqual(frappe.db.get_value("Scan Code", code, "scan_count"), 0)
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_doctype": SOURCE_DOCTYPE,
				"source_name": SOURCE_NAME,
				"scan_code": code,
				"result": "Failure",
			},
			fields=["device_info", "error_message"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["device_info"], "Rescan")
		self.assertIn("already been used", log["error_message"])

	def test_dispatch_rejects_source_doctype_mismatch_and_logs_failure(self):
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

		# The source does not exist: a real commit would persist an orphan Scan Code.
		with (
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch.object(frappe.db, "commit") as commit,
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(code=sc.name, device_info="Desktop")

		commit.assert_called_once()
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_doctype": "User",
				"source_name": "Administrator",
				"result": "Failure",
			},
			fields=["name", "source_doctype", "source_name", "error_message"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["source_doctype"], "User")
		self.assertEqual(log["source_name"], "Administrator")
		self.assertIn("source doctype", log["error_message"].lower())

	def test_dispatch_handler_failure_rolls_back_partial_writes(self):
		code = self._make_scan_code(
			action_key="create_purchase_receipt_partial_writes",
			source_doctype=SOURCE_DOCTYPE,
			source_name=SOURCE_NAME,
		)
		inserted = {}

		def failing_handler(handler_method, source_doctype, source_name, payload):
			todo = frappe.get_doc({"doctype": "ToDo", "description": "Partial handler write"}).insert(
				ignore_permissions=True
			)
			inserted["todo_name"] = todo.name
			raise RuntimeError("handler failed mid-insert")

		with (
			patched_action(
				"create_purchase_receipt_partial_writes",
				"asn_module.handlers.purchase_receipt.create_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=failing_handler),
		):
			with self.assertRaises(RuntimeError):
				dispatch(code=code, device_info="Desktop")

		self.assertFalse(frappe.db.exists("ToDo", inserted["todo_name"]))
		log = frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt_partial_writes",
				"source_name": SOURCE_NAME,
				"result": "Failure",
			},
			fields=["scan_code", "error_message"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log["scan_code"], code)
		self.assertIn("handler failed mid-insert", log["error_message"])

	def test_dispatch_raises_permission_denied_for_users_without_allowed_roles(self):
		code = self._make_scan_code()

		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
				roles=["Stock User", "Stock Manager"],
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["Accounts User"]),
		):
			with self.assertRaises(PermissionDeniedError):
				dispatch(code=code)

	def test_dispatch_no_duplicate_success_scan_log_when_handler_returns_scan_log(self):
		code = self._make_scan_code(
			action_key="emit_scan_log_success",
			source_doctype=SOURCE_DOCTYPE,
			source_name=SOURCE_NAME,
		)
		frappe.local.flags.commit = False

		success_filters = {
			"action": "emit_scan_log_success",
			"source_name": SOURCE_NAME,
			"result": "Success",
		}
		success_logs_before = frappe.db.count("Scan Log", success_filters)

		def call_handler(handler_method, source_doctype, source_name, payload):
			log = frappe.get_doc(
				{
					"doctype": "Scan Log",
					"action": payload["action"],
					"source_doctype": source_doctype,
					"source_name": source_name,
					"scan_code": payload.get("scan_code"),
					"result": "Success",
					"device_info": payload.get("device_info") or "Desktop",
				}
			).insert(ignore_permissions=True)
			return {
				"doctype": "Scan Log",
				"name": log.name,
				"url": f"/app/scan-log/{log.name}",
				"message": "emit scan log test",
			}

		with (
			patched_action(
				"emit_scan_log_success",
				"asn_module.handlers.putaway.confirm_putaway",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=call_handler),
		):
			result = dispatch(code=code, device_info="Handheld-Scanner-X")

		self.assertEqual(result["doctype"], "Scan Log")
		self.assertEqual(frappe.db.count("Scan Log", success_filters), success_logs_before + 1)
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.device_info, "Handheld-Scanner-X")
		self.assertTrue(frappe.local.flags.commit)


class TestDispatchFailureCommit(FrappeTestCase):
	"""A failing dispatch commits so its Scan Log survives a rollback. Commits for real."""

	def setUp(self):
		super().setUp()
		self.codes = []
		self.addCleanup(self._purge_committed_rows)

	def _purge_committed_rows(self):
		frappe.db.rollback()
		frappe.db.delete("Scan Log", {"scan_code": ("in", self.codes)})
		frappe.db.delete("Scan Code", {"name": ("in", self.codes)})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - purge what this class really committed

	def _make_scan_code(self, action_key):
		code = get_or_create_scan_code(action_key, SOURCE_DOCTYPE, SOURCE_NAME)
		self.codes.append(code)
		return code

	def test_dispatch_rejects_partial_handler_result_and_logs_failure(self):
		code = self._make_scan_code("create_purchase_receipt_partial_result")

		with (
			patched_action(
				"create_purchase_receipt_partial_result",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch(
				"asn_module.qr_engine.dispatch._call_handler",
				return_value={"doctype": "ToDo", "name": "TODO-001"},
			),
		):
			with self.assertRaises(frappe.ValidationError):
				dispatch(code=code, device_info="Desktop")

		frappe.db.rollback()
		success_logs = frappe.get_all(
			"Scan Log",
			filters={"scan_code": code, "result": "Success"},
			pluck="name",
		)
		self.assertFalse(success_logs)

		failure_logs = frappe.get_all(
			"Scan Log",
			filters={"scan_code": code, "result": "Failure"},
			fields=["error_message"],
		)
		self.assertEqual(len(failure_logs), 1)
		self.assertIn("handler result", failure_logs[0]["error_message"].lower())

	def test_dispatch_logs_failure_when_handler_raises(self):
		code = self._make_scan_code("create_purchase_receipt_failure")

		with (
			patched_action(
				"create_purchase_receipt_failure",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=ValueError("handler failed")),
		):
			with self.assertRaises(ValueError):
				dispatch(code=code, device_info="Desktop")

		frappe.db.rollback()
		log = frappe.get_all(
			"Scan Log",
			filters={"scan_code": code, "result": "Failure"},
			fields=["device_info", "error_message"],
		)[0]
		self.assertEqual(log["device_info"], "Desktop")
		self.assertIn("handler failed", log["error_message"])
