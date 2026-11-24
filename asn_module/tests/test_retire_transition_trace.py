import frappe

from asn_module.patches.retire_transition_trace import execute
from asn_module.tests.compat import IntegrationTestCase


class TestRetireTransitionTrace(IntegrationTestCase):
	def test_patch_leaves_no_trace_report_doctype_or_table_and_can_rerun(self):
		execute()
		execute()

		self.assertFalse(frappe.db.exists("Report", "ASN Item Transition Trace"))
		self.assertFalse(frappe.db.exists("DocType", "ASN Transition Log"))
		self.assertFalse(frappe.db.table_exists("ASN Transition Log"))
