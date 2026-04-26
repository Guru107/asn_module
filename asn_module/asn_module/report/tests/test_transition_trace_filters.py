from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.traceability import emit_asn_item_transition
from asn_module.utils.test_setup import before_tests


class _ReportTestBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		cls._asn = asn
		cls._asn_name = asn.name
		cls._asn_item = asn.items[0].name
		cls._item_code = asn.items[0].item_code

		po2 = create_purchase_order(qty=5)
		asn2 = make_test_asn(purchase_order=po2, qty=5)
		asn2.insert(ignore_permissions=True)
		cls._asn2 = asn2
		cls._asn2_name = asn2.name

	def _emit(self, **kwargs):
		defaults = dict(
			asn=self._asn_name,
			asn_item=self._asn_item,
			item_code=self._item_code,
			state="Test",
			transition_status="OK",
			ref_doctype="ASN",
			ref_name=self._asn_name,
		)
		defaults.update(kwargs)
		doc = frappe.get_doc(
			{
				"doctype": "ASN Transition Log",
				**defaults,
				"event_ts": frappe.utils.now_datetime(),
				"actor": frappe.session.user,
			}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		return doc.name


class TestTransitionTraceFilters(_ReportTestBase):
	def test_execute_filters_by_asn(self):
		self._emit(state="ASN Filter Test", asn=self._asn_name)
		self._emit(state="ASN Filter Other", asn=self._asn2_name)

		_columns, rows = execute({"asn": self._asn_name})

		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(row[1], self._asn_name)

	def test_execute_filters_by_item_code(self):
		self._emit(state="Item Code Filter Test", item_code=self._item_code)

		_columns, rows = execute({"item_code": self._item_code})

		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(row[3], self._item_code)

	def test_execute_filters_by_to_date_excludes_future_rows(self):
		self._emit(state="To Date Filter Test")
		past_date = frappe.utils.add_days(frappe.utils.today(), -30)

		_columns, rows = execute({"to_date": past_date})

		self.assertEqual(rows, [])

	def test_execute_filters_by_ref_doctype(self):
		self._emit(state="RefDoctype Test", ref_doctype="Purchase Receipt", ref_name=self._asn2_name)
		self._emit(state="RefDoctype Test ASN", ref_doctype="ASN", ref_name=self._asn_name)

		_columns, rows = execute({"ref_doctype": "ASN"})

		self.assertIsInstance(rows, list)
		self.assertTrue(len(rows) > 0, "Expected at least one row with ref_doctype=ASN")
		for row in rows:
			ref_display = row[6]
			self.assertIn("ASN", ref_display, f"Expected 'ASN' in ref_display, got: {ref_display}")

	def test_execute_filters_by_ref_name(self):
		target_name = self._asn2_name

		self._emit(state="First RefName Test", ref_doctype="ASN", ref_name=self._asn_name)
		self._emit(state="Second RefName Test", ref_doctype="ASN", ref_name=target_name)

		_columns, rows = execute({"ref_name": target_name})

		self.assertIsInstance(rows, list)
		self.assertTrue(len(rows) > 0, f"Expected at least one row with ref_name={target_name}")
		for row in rows:
			ref_display = row[6]
			self.assertIn(
				target_name,
				ref_display,
				f"Expected ref_name '{target_name}' in ref_display, got: {ref_display}",
			)

	def test_execute_filters_by_date_range_excludes_outside(self):
		self._emit(state="Date Range Test")

		future_date = frappe.utils.add_days(frappe.utils.today(), 30)
		_columns, rows = execute({"from_date": future_date})

		self.assertIsInstance(rows, list)
		self.assertEqual(len(rows), 0, f"Expected no rows for future date {future_date}")

	def test_execute_filters_by_error_status_only(self):
		self._emit(state="OK Status Test", transition_status="OK")
		self._emit(state="Error Status Test", transition_status="Error", error_code="TEST-ERR")

		_columns, rows = execute({"failures_only": True})

		self.assertIsInstance(rows, list)
		self.assertTrue(len(rows) > 0, "Expected at least one row with transition_status=Error")
		for row in rows:
			self.assertEqual(row[5], "Error", f"Expected transition_status='Error', got: {row[5]}")

	def test_execute_filters_by_search_text_partial_match(self):
		search_term = "UNIQUE-SEARCH-TERM-XY7Z"

		self._emit(state="Search Test State", details=f"ASN-ITEM-{search_term}-DETAILS")

		_columns, rows = execute({"search": search_term})

		self.assertIsInstance(rows, list)
		self.assertTrue(len(rows) > 0, f"Expected at least one row matching search '{search_term}'")
		found = False
		for row in rows:
			details = row[9]
			if search_term in (details or ""):
				found = True
				break
		self.assertTrue(found, f"Expected to find search term '{search_term}' in details")
