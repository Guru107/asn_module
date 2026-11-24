from unittest.mock import patch

import frappe

from asn_module.patches.retire_transition_trace import execute
from asn_module.tests.compat import IntegrationTestCase


class TestRetireTransitionTrace(IntegrationTestCase):
	def test_rerun_after_the_drop_finds_nothing_and_does_not_commit(self):
		self.assertFalse(
			frappe.db.table_exists("ASN Transition Log", cached=False),
			"migrate runs the patch, so the table is gone before tests run",
		)

		# sql_ddl commits first; reaching it here would commit the test transaction.
		with patch.object(frappe.db, "sql_ddl") as sql_ddl:
			execute()

		sql_ddl.assert_not_called()
		self.assertFalse(frappe.db.exists("Report", "ASN Item Transition Trace"))
		self.assertFalse(frappe.db.exists("DocType", "ASN Transition Log"))
