import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.traceability import emit_asn_item_transition


class TestAsnItemTransitionTraceReport(FrappeTestCase):
	def test_execute_returns_columns_and_rows_without_filters(self):
		columns, rows = execute({})
		self.assertEqual(len(columns), 10)
		self.assertIsInstance(rows, list)

	def test_execute_respects_limit(self):
		_, rows = execute({"limit_page_length": 5, "limit_start": 0})
		self.assertLessEqual(len(rows), 5)

	def test_filter_by_item_code(self):
		asn = "ASN-RPT-" + frappe.generate_hash(length=6)
		emit_asn_item_transition(
			asn=asn,
			item_code="FILTER-ITEM-001",
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			item_code="FILTER-ITEM-002",
			state="Submitted",
		)
		_, rows = execute({"item_code": "FILTER-ITEM-001"})
		for row in rows:
			self.assertEqual(row[3], "FILTER-ITEM-001")

	def test_filter_by_state(self):
		asn = "ASN-RPT-ST-" + frappe.generate_hash(length=6)
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			state="Received",
		)
		_, rows = execute({"state": "Submitted"})
		for row in rows:
			self.assertEqual(row[4], "Submitted")

	def test_failures_only_filter(self):
		asn = "ASN-RPT-FO-" + frappe.generate_hash(length=6)
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			transition_status="OK",
		)
		emit_asn_item_transition(
			asn=asn,
			state="Received",
			transition_status="Error",
		)
		_, rows = execute({"failures_only": True})
		for row in rows:
			self.assertEqual(row[5], "Error")

	def test_search_text_filter(self):
		asn = "ASN-RPT-SR-" + frappe.generate_hash(length=6)
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			details="unique_search_marker_xyz",
		)
		_, rows = execute({"search": "unique_search_marker_xyz"})
		self.assertTrue(any("unique_search_marker_xyz" in str(row) for row in rows))

	def test_limit_clamped_to_500(self):
		_, rows = execute({"limit_page_length": 999})
		self.assertLessEqual(len(rows), 500)

	def test_limit_clamped_to_1_minimum(self):
		_, rows = execute({"limit_page_length": 0})
		self.assertLessEqual(len(rows), 1)
