import secrets
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from asn_module.qr_engine.dispatch import (
	DISPATCH_RATE_LIMIT,
	ActionNotFoundError,
	PermissionDeniedError,
	_latest_success_document,
	_resolve_action,
	dispatch,
	record_failed_scan,
)
from asn_module.qr_engine.scan_codes import (
	SCAN_CODE_ALPHABET,
	SCAN_CODE_LENGTH,
	_random_scan_code_value,
)
from asn_module.tests.compat import IntegrationTestCase
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
from asn_module.utils.test_setup import before_tests, inline_enqueue_patcher

SOURCE_DOCTYPE = "DocType"
SOURCE_NAME = "User"


def _fresh_scan_code(action_key, source_doctype=SOURCE_DOCTYPE, source_name=SOURCE_NAME):
	# Never reuse an Active row a past run left behind: its Scan Logs would count here.
	return (
		frappe.get_doc(
			{
				"doctype": "Scan Code",
				"scan_code": _random_scan_code_value(),
				"action_key": action_key,
				"source_doctype": source_doctype,
				"source_name": source_name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


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


class TestDispatch(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		# The failure log is a background job; run it in this transaction. The job
		# itself is covered by TestDispatchFailureLog below.
		patcher = inline_enqueue_patcher()
		patcher.start()
		self.addCleanup(patcher.stop)

	def _make_scan_code(
		self,
		action_key="create_purchase_receipt",
		source_doctype=SOURCE_DOCTYPE,
		source_name=SOURCE_NAME,
	):
		return _fresh_scan_code(action_key, source_doctype, source_name)

	def test_resolve_action_returns_the_code_defined_action(self):
		action = _resolve_action("create_purchase_receipt")

		self.assertEqual(action["handler"], "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn")
		self.assertEqual(action["source_doctype"], "ASN")
		self.assertEqual(action["allowed_roles"], ["Stock User", "Stock Manager"])

	def test_resolve_action_raises_for_unknown_action(self):
		with self.assertRaises(ActionNotFoundError):
			_resolve_action("unknown_action")

	def test_dispatch_refuses_retired_quality_inspection_actions(self):
		for action_key in ("create_stock_transfer", "create_purchase_return"):
			code = self._make_scan_code(action_key=action_key)
			with self.assertRaises(ActionNotFoundError):
				dispatch(code=code, device_info="test")

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
		self.assertFalse(frappe.local.flags.commit)
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
		current_code = self._make_scan_code()
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

		commit.assert_not_called()
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
				"asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=call_handler),
		):
			result = dispatch(code=code, device_info="Handheld-Scanner-X")

		self.assertEqual(result["doctype"], "Scan Log")
		self.assertEqual(frappe.db.count("Scan Log", success_filters), success_logs_before + 1)
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.device_info, "Handheld-Scanner-X")
		self.assertFalse(frappe.local.flags.commit)


class TestDispatchFailureLog(IntegrationTestCase):
	"""A failing dispatch commits nothing; a separate job writes its Failure Scan Log."""

	def _failing_dispatch(self, action_key, error):
		code = _fresh_scan_code(action_key)
		with (
			patched_action(action_key, "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=error),
			self.assertRaises(type(error)),
		):
			dispatch(code=code, device_info="Desktop")
		return code

	def test_failure_is_logged_by_a_separate_job_without_committing(self):
		with patch("frappe.enqueue") as enqueue, patch.object(frappe.db, "commit") as commit:
			code = self._failing_dispatch("create_purchase_receipt_failure", ValueError("handler failed"))

		commit.assert_not_called()
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args, ("asn_module.qr_engine.dispatch.record_failed_scan",))
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["scan_code"], code)
		self.assertEqual(kwargs["device_info"], "Desktop")
		self.assertIn("handler failed", kwargs["error_message"])
		# Enqueued immediately: a job queued after commit would be dropped by the rollback.
		self.assertFalse(kwargs.get("enqueue_after_commit"))
		self.assertFalse(frappe.db.exists("Scan Log", {"scan_code": code}))

	def test_record_failed_scan_writes_the_failure_log(self):
		code = _fresh_scan_code("create_purchase_receipt_failure")

		record_failed_scan(
			action="create_purchase_receipt_failure",
			source_doctype=SOURCE_DOCTYPE,
			source_name=SOURCE_NAME,
			device_info="Desktop",
			scan_code=code,
			error_message="handler failed",
		)

		log = frappe.get_all(
			"Scan Log",
			filters={"scan_code": code, "result": "Failure"},
			fields=["device_info", "error_message", "source_doctype", "source_name"],
		)[0]
		self.assertEqual(log["device_info"], "Desktop")
		self.assertIn("handler failed", log["error_message"])
		self.assertEqual((log["source_doctype"], log["source_name"]), (SOURCE_DOCTYPE, SOURCE_NAME))

	def test_rejected_partial_handler_result_is_logged_as_failure(self):
		code = _fresh_scan_code("create_purchase_receipt_partial_result")

		with (
			inline_enqueue_patcher(),
			patched_action(
				"create_purchase_receipt_partial_result",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
			),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch(
				"asn_module.qr_engine.dispatch._call_handler",
				return_value={"doctype": "ToDo", "name": "TODO-001"},
			),
			self.assertRaises(frappe.ValidationError),
		):
			dispatch(code=code, device_info="Desktop")

		self.assertFalse(frappe.db.exists("Scan Log", {"scan_code": code, "result": "Success"}))
		failure_logs = frappe.get_all(
			"Scan Log", filters={"scan_code": code, "result": "Failure"}, fields=["error_message"]
		)
		self.assertEqual(len(failure_logs), 1)
		self.assertIn("handler result", failure_logs[0]["error_message"].lower())


class TestDispatchEndpointAccess(IntegrationTestCase):
	def test_dispatch_is_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[dispatch], ["POST"])

	def test_website_user_is_rejected_without_writing_a_scan_log(self):
		email = f"portal.scan.{frappe.generate_hash(length=8)}@asn-module.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Portal",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		logs_before = frappe.db.count("Scan Log")
		self.addCleanup(frappe.set_user, frappe.session.user)

		frappe.set_user(email)
		with patch("frappe.enqueue") as enqueue, self.assertRaises(frappe.PermissionError):
			dispatch(code="garbage", device_info="Desktop")
		frappe.set_user("Administrator")

		enqueue.assert_not_called()
		self.assertEqual(frappe.db.count("Scan Log"), logs_before)

	def test_dispatch_is_rate_limited_per_ip(self):
		# rate_limit is a no-op without a request, so fake one; the cache is callable (v15) or not (v16).
		cache = MagicMock()
		cache.return_value = cache
		cache.get.return_value = None
		cache.incrby.return_value = DISPATCH_RATE_LIMIT + 1
		with (
			patch.object(frappe, "request", MagicMock(), create=True),
			patch.object(frappe.local, "request_ip", "10.0.0.1", create=True),
			patch.object(frappe, "cache", cache),
			patch("frappe.enqueue") as enqueue,
			self.assertRaises(frappe.RateLimitExceededError),
		):
			dispatch(code="garbage", device_info="Desktop")

		enqueue.assert_not_called()


class TestDispatchSourcePermission(IntegrationTestCase):
	"""A role alone is not enough: the user must also be allowed to read the scanned document."""

	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		cls.email = ensure_integration_user()

	def setUp(self):
		super().setUp()
		patcher = inline_enqueue_patcher()
		patcher.start()
		self.addCleanup(patcher.stop)

	def _warehouse(self, warehouse_name):
		return (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": warehouse_name,
					"company": frappe.db.get_value("Company", {}, "name"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _scan(self, warehouse):
		code = _fresh_scan_code("create_purchase_receipt", "Warehouse", warehouse)
		handler_result = {"doctype": "Warehouse", "name": warehouse, "url": f"/app/warehouse/{warehouse}"}
		with (
			patched_action(
				"create_purchase_receipt",
				"asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
				source_doctype="Warehouse",
				roles=["Stock User"],
			),
			patch("asn_module.qr_engine.dispatch._call_handler", return_value=handler_result),
			integration_user_context(self.email),
		):
			return dispatch(code=code)

	def test_a_source_outside_the_users_permissions_is_refused_and_a_permitted_one_works(self):
		own = self._warehouse("Scan Perm Own")
		other = self._warehouse("Scan Perm Other")
		frappe.permissions.add_user_permission("Warehouse", own, self.email, ignore_permissions=True)
		# The rollback does not clear the cached User Permissions; later tests reuse this user.
		self.addCleanup(frappe.clear_cache, user=self.email)

		self.assertTrue(self._scan(own)["success"])
		with self.assertRaises(frappe.PermissionError):
			self._scan(other)
