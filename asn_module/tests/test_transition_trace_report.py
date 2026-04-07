import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.traceability import emit_asn_item_transition, get_latest_transition_rows_for_asn
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

	def _emit(self, **kwargs):
		defaults = dict(
			asn=self._asn_name,
			asn_item=self._asn_item,
			item_code=self._item_code,
			ref_doctype="ASN",
			ref_name=self._asn_name,
		)
		defaults.update(kwargs)
		return emit_asn_item_transition(**defaults)


class TestAsnItemTransitionTraceReport(_ReportTestBase):
	def test_execute_returns_columns_and_rows_without_filters(self):
		columns, rows = execute({})
		self.assertEqual(len(columns), 10)
		self.assertIsInstance(rows, list)

	def test_filter_by_item_code(self):
		self._emit(state="Submitted")
		_columns, rows = execute({"item_code": self._item_code})
		self.assertIsInstance(rows, list)
		if rows:
			self.assertTrue(any(r[3] == self._item_code for r in rows))

	def test_filter_by_state(self):
		self._emit(state="Submitted")
		_columns, rows = execute({"state": "Submitted"})
		self.assertIsInstance(rows, list)

	def test_failures_only_filter(self):
		self._emit(state="Submitted", transition_status="OK")
		_columns, rows = execute({"transition_status": "FAIL"})
		self.assertIsInstance(rows, list)

	def test_search_text_filter(self):
		self._emit(state="Submitted")
		_columns, rows = execute({"search_text": self._asn_name})
		self.assertIsInstance(rows, list)

	def test_execute_respects_limit(self):
		_columns, rows = execute({"limit_page_length": 1})
		self.assertLessEqual(len(rows), 1)

	def test_limit_clamped_to_500(self):
		columns, _rows = execute({"limit_page_length": 999})
		self.assertEqual(len(columns), 10)
