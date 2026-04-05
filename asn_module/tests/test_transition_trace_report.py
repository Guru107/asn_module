import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute


class TestAsnItemTransitionTraceReport(FrappeTestCase):
	def test_execute_returns_columns_and_rows_without_filters(self):
		columns, rows = execute({})
		self.assertEqual(len(columns), 10)
		self.assertIsInstance(rows, list)

	def test_execute_respects_limit(self):
		_, rows = execute({"limit_page_length": 5, "limit_start": 0})
		self.assertLessEqual(len(rows), 5)
