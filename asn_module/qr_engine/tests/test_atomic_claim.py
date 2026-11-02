"""Regression tests for the atomic scan-code claim (issue #75).

Two stations scanning one single-use code inside the handler window must not
both create a draft: the code is claimed ``Active`` → ``Used`` in one
conditional UPDATE before the handler runs, and the claim rolls back with the
dispatch savepoint when the handler fails. ASN actions reopen their own drafts
from Used codes and never claim.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import (
	claim_scan_code_for_single_use,
	get_or_create_scan_code,
)
from asn_module.qr_engine.tests.test_dispatch import patched_action

HANDLER = "asn_module.handlers.purchase_receipt.create_from_asn"


def _make_todo(description):
	return frappe.get_doc({"doctype": "ToDo", "description": description}).insert(ignore_permissions=True)


class TestAtomicScanClaim(FrappeTestCase):
	def _make_scan_code(self, action_key, source_doctype="DocType", source_name="User"):
		return get_or_create_scan_code(action_key, source_doctype, source_name)

	def test_second_claim_on_same_code_loses(self):
		"""The conditional UPDATE changes exactly one row; the loser gets rowcount 0."""
		code = self._make_scan_code("claim_atomicity_probe")

		claim_scan_code_for_single_use(code)
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")

		with self.assertRaises(frappe.ValidationError) as cm:
			claim_scan_code_for_single_use(code)
		self.assertIn("already been used", str(cm.exception))

	def test_concurrent_dispatch_creates_exactly_one_draft(self):
		"""A second dispatch inside the first one's handler window must lose the race."""
		code = self._make_scan_code("race_single_use_action")
		handler_calls = []
		drafts = []
		late_results = []
		loser_errors = []

		def racing_handler(handler_method, source_doctype, source_name, payload):
			handler_calls.append(payload["scan_code"])
			if len(handler_calls) == 1:
				# Station B scans the same code while station A's handler is still
				# running — the race window from the issue.
				try:
					late_results.append(dispatch(code=code, device_info="Station-B"))
				except frappe.ValidationError as exc:
					loser_errors.append(str(exc))
			todo = _make_todo("Race draft")
			drafts.append(todo.name)
			return {"doctype": "ToDo", "name": todo.name, "url": todo.get_url()}

		with (
			patched_action("race_single_use_action", HANDLER),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=racing_handler),
		):
			result = dispatch(code=code, device_info="Station-A")

		self.assertTrue(result["success"])
		self.assertEqual(len(handler_calls), 1)
		self.assertEqual(len(drafts), 1)
		self.assertFalse(late_results)
		self.assertEqual(len(loser_errors), 1)
		self.assertIn("already been used", loser_errors[0])
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")

	def test_failed_handler_reverts_claim_and_code_is_rescannable(self):
		code = self._make_scan_code("claim_rollback_action")
		observed = {}

		def failing_handler(handler_method, source_doctype, source_name, payload):
			observed["status_during_handler"] = frappe.db.get_value("Scan Code", code, "status")
			raise RuntimeError("handler failed mid-claim")

		with (
			patched_action("claim_rollback_action", HANDLER),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=failing_handler),
		):
			with self.assertRaises(RuntimeError):
				dispatch(code=code, device_info="Desktop")

		self.assertEqual(observed["status_during_handler"], "Used")
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

		def ok_handler(handler_method, source_doctype, source_name, payload):
			todo = _make_todo("Rescan draft")
			return {"doctype": "ToDo", "name": todo.name, "url": todo.get_url()}

		with (
			patched_action("claim_rollback_action", HANDLER),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=ok_handler),
		):
			result = dispatch(code=code, device_info="Rescan")

		self.assertTrue(result["success"])
		self.assertEqual(result["doctype"], "ToDo")

	def test_asn_action_rescan_reopens_draft_without_claiming(self):
		"""ASN scans reopen their own draft from a Used code; they must not claim."""
		code = self._make_scan_code("create_purchase_receipt", "ASN", "Fake-ASN-For-Test")
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		todo = _make_todo("Existing ASN draft")

		def reopening_handler(handler_method, source_doctype, source_name, payload):
			return {"doctype": "ToDo", "name": todo.name, "url": todo.get_url()}

		with (
			patched_action("create_purchase_receipt", HANDLER, source_doctype="ASN"),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=reopening_handler),
			patch("asn_module.qr_engine.dispatch.claim_scan_code_for_single_use") as claim,
		):
			result = dispatch(code=code, device_info="Rescan")

		claim.assert_not_called()
		self.assertTrue(result["success"])
		self.assertEqual(result["doctype"], "ToDo")
		self.assertEqual(result["name"], todo.name)
