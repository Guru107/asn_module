"""Regression tests for the atomic scan-code claim (issue #75).

Two stations scanning one single-use code inside the handler window must not
both create a draft: the code is claimed ``Active`` → ``Used`` in one
conditional UPDATE before the handler runs, and the claim rolls back with the
dispatch savepoint when the handler fails. ASN actions reopen their own drafts
from Used codes and never claim.
"""

import threading
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order_with_fiscal_dates,
	make_test_asn,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import claim_scan_code_for_single_use, get_or_create_scan_code
from asn_module.qr_engine.tests.test_dispatch import patched_action
from asn_module.utils.test_setup import before_tests

HANDLER = "asn_module.handlers.purchase_receipt.create_from_asn"


def _make_todo(description):
	return frappe.get_doc({"doctype": "ToDo", "description": description}).insert(ignore_permissions=True)


def _make_scan_code(action_key, source_doctype="DocType", source_name="User"):
	# Fake sources need ignore_links; the dispatch tests do the same.
	from asn_module.qr_engine.scan_codes import _random_scan_code_value

	doc = frappe.get_doc(
		{
			"doctype": "Scan Code",
			"scan_code": _random_scan_code_value(),
			"action_key": action_key,
			"source_doctype": source_doctype,
			"source_name": source_name,
		}
	)
	doc.insert(ignore_permissions=True, ignore_links=True)
	return doc.name


@contextmanager
def dispatch_with_handler(action_key, handler, *, source_doctype="DocType"):
	"""Patch the action registry, the role check, and the handler call for a dispatch."""
	with (
		patched_action(action_key, HANDLER, source_doctype=source_doctype),
		patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
		patch("asn_module.qr_engine.dispatch._call_handler", side_effect=handler),
	):
		yield


class TestAtomicScanClaim(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def test_second_claim_on_same_code_throws_already_used(self):
		"""The conditional UPDATE changes exactly one row; the loser changes none."""
		code = _make_scan_code("claim_atomicity_probe")

		claim_scan_code_for_single_use(code)
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")

		with self.assertRaises(frappe.ValidationError) as cm:
			claim_scan_code_for_single_use(code)
		self.assertIn("already been used", str(cm.exception))

	def test_claim_snapshot_conflict_throws_already_used(self):
		"""InnoDB 1020 (stale REPEATABLE READ snapshot on a raced row) is a lost race."""
		code = _make_scan_code("claim_snapshot_conflict_probe")

		with (
			patch(
				"asn_module.qr_engine.scan_codes.frappe.db.sql",
				side_effect=frappe.QueryDeadlockError("1020"),
			),
			self.assertRaises(frappe.ValidationError) as cm,
		):
			claim_scan_code_for_single_use(code)

		self.assertIn("already been used", str(cm.exception))
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

	def test_concurrent_dispatch_on_two_connections_creates_exactly_one_draft(self):
		"""Two stations on separate connections: the loser's claim UPDATE blocks on
		the winner's row lock and changes zero rows once the winner commits."""
		code = _make_scan_code("race_single_use_action")
		frappe.db.commit()  # the second connection must see the code row
		site = frappe.local.site

		drafts = []
		winner_claimed = threading.Event()
		loser_started = threading.Event()
		loser_result = {}

		def winning_handler(*args):
			# Runs on the winner's connection, after its claim holds the row lock.
			todo = _make_todo("Race draft")
			drafts.append(todo.name)
			winner_claimed.set()
			# Give the loser time to reach its blocked UPDATE before we commit.
			loser_started.wait(timeout=10)
			frappe.db.sql("SELECT SLEEP(1)")
			return {"doctype": "ToDo", "name": todo.name, "url": todo.get_url()}

		def losing_station():
			try:
				frappe.init(site=site)
				frappe.connect()
				frappe.set_user("Administrator")
				winner_claimed.wait(timeout=10)
				try:
					loser_result["outcome"] = dispatch(code=code, device_info="Station-B")
					frappe.db.commit()
				except Exception as exc:  # surfaced via assertions below
					loser_result["error"] = exc
					frappe.db.rollback()
			except Exception as exc:
				loser_result["error"] = exc
			finally:
				frappe.destroy()

		try:
			with dispatch_with_handler("race_single_use_action", winning_handler):
				station_b = threading.Thread(target=losing_station)
				station_b.start()
				loser_started.set()  # loser may start as soon as the winner holds the claim
				result = dispatch(code=code, device_info="Station-A")
				frappe.db.commit()
				station_b.join(timeout=60)

			self.assertTrue(result["success"])
			self.assertNotIn("outcome", loser_result)
			self.assertIsInstance(loser_result.get("error"), frappe.ValidationError)
			self.assertIn("already been used", str(loser_result["error"]))
			self.assertEqual(len(drafts), 1)
			self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Used")
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Scan Log", {"scan_code": code})
			for draft in drafts:
				frappe.delete_doc("ToDo", draft, force=True, ignore_permissions=True)
			frappe.delete_doc("Scan Code", code, force=True, ignore_permissions=True)
			frappe.db.commit()

	def test_failed_handler_reverts_claim_and_code_is_rescannable(self):
		code = _make_scan_code("claim_rollback_action")
		observed = {}

		def failing_handler(*args):
			observed["status_during_handler"] = frappe.db.get_value("Scan Code", code, "status")
			raise RuntimeError("handler failed mid-claim")

		with dispatch_with_handler("claim_rollback_action", failing_handler):
			with self.assertRaises(RuntimeError):
				dispatch(code=code, device_info="Desktop")

		self.assertEqual(observed["status_during_handler"], "Used")
		self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Active")

		def ok_handler(*args):
			todo = _make_todo("Rescan draft")
			return {"doctype": "ToDo", "name": todo.name, "url": todo.get_url()}

		with dispatch_with_handler("claim_rollback_action", ok_handler):
			result = dispatch(code=code, device_info="Rescan")

		self.assertTrue(result["success"])
		self.assertEqual(result["doctype"], "ToDo")

	def test_failed_rollback_does_not_commit_the_claim(self):
		"""When rolling back partial writes itself fails, the except path must not
		commit: committing would persist the stale claim and the partial writes."""
		code = _make_scan_code("claim_rollback_failure_action")

		def failing_handler(*args):
			raise RuntimeError("handler failed mid-claim")

		with (
			patched_action("claim_rollback_failure_action", HANDLER),
			patch("asn_module.qr_engine.dispatch.frappe.get_roles", return_value=["System Manager"]),
			patch("asn_module.qr_engine.dispatch._call_handler", side_effect=failing_handler),
			patch(
				"asn_module.qr_engine.dispatch.frappe.db.rollback",
				side_effect=Exception("savepoint rollback failed"),
			),
			patch("asn_module.qr_engine.dispatch.frappe.db.commit") as commit,
		):
			with self.assertRaises(RuntimeError):
				dispatch(code=code, device_info="Desktop")

		commit.assert_not_called()

	def test_asn_action_rescan_reopens_draft_without_claiming(self):
		"""ASN scans reopen their own draft from a Used code; they must not claim."""
		purchase_order = create_purchase_order_with_fiscal_dates(qty=2)
		asn = make_test_asn(purchase_order=purchase_order, qty=1)
		asn.insert(ignore_permissions=True)

		code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)
		todo = _make_todo("Existing ASN draft")

		def reopening_handler(*args):
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
		# A real dispatch happened: scan count bumped and the success is logged
		# against the reopened draft.
		self.assertEqual(frappe.db.get_value("Scan Code", code, "scan_count"), 1)
		log = frappe.get_all(
			"Scan Log",
			filters={"scan_code": code, "result": "Success"},
			fields=["result_doctype", "result_name"],
			limit=1,
		)
		self.assertEqual(log[0].result_doctype, "ToDo")
		self.assertEqual(log[0].result_name, todo.name)
