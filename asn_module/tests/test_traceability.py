import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.traceability import (
	_idempotency_key,
	emit_asn_item_transition,
	get_latest_transition_rows_for_asn,
)
from asn_module.utils.test_setup import before_tests


class _TraceabilityTestBase(FrappeTestCase):
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


class TestIdempotencyKey(FrappeTestCase):
	def test_deterministic(self):
		k1 = _idempotency_key("ASN-001", "ASN-ITEM-001", "Received", "Purchase Receipt", "PR-001")
		k2 = _idempotency_key("ASN-001", "ASN-ITEM-001", "Received", "Purchase Receipt", "PR-001")
		self.assertEqual(k1, k2)

	def test_varies_with_asn(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-001")
		k2 = _idempotency_key("ASN-002", "ITEM-1", "Received", "PR", "PR-001")
		self.assertNotEqual(k1, k2)

	def test_varies_with_state(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", None, None)
		k2 = _idempotency_key("ASN-001", "ITEM-1", "Submitted", None, None)
		self.assertNotEqual(k1, k2)

	def test_varies_with_ref_name(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-001")
		k2 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-002")
		self.assertNotEqual(k1, k2)


class TestEmitAsnItemTransition(_TraceabilityTestBase):
	def test_creates_row(self):
		name = self._emit(state="Received")
		self.assertTrue(name)
		doc = frappe.get_doc("ASN Transition Log", name)
		self.assertEqual(doc.asn, self._asn_name)
		self.assertEqual(doc.state, "Received")

	def test_deduplicates_on_replay(self):
		first = self._emit(state="Submitted")
		second = self._emit(state="Submitted")
		self.assertIsNotNone(first)
		self.assertIsNone(second)

	def test_returns_none_on_empty_asn(self):
		result = emit_asn_item_transition(asn="", state="Submitted")
		self.assertIsNone(result)

	def test_different_ref_name_same_state_creates_new_row(self):
		po2 = create_purchase_order(qty=5)
		asn2 = make_test_asn(purchase_order=po2, qty=5)
		asn2.insert(ignore_permissions=True)
		po3 = create_purchase_order(qty=5)
		asn3 = make_test_asn(purchase_order=po3, qty=5)
		asn3.insert(ignore_permissions=True)
		first = self._emit(state="Received", ref_doctype="ASN", ref_name=asn2.name)
		second = self._emit(state="Received", ref_doctype="ASN", ref_name=asn3.name)
		self.assertIsNotNone(first)
		self.assertIsNotNone(second)


class TestGetLatestTransitionRowsForAsn(_TraceabilityTestBase):
	def test_returns_latest_per_item(self):
		self._emit(state="Submitted", asn_item=self._asn_item)
		self._emit(state="Received", asn_item=self._asn_item)
		po2 = create_purchase_order(qty=5)
		asn2 = make_test_asn(purchase_order=po2, qty=5)
		asn2.insert(ignore_permissions=True)
		self._emit(
			state="Submitted", asn=asn2.name, asn_item=asn2.items[0].name, item_code=asn2.items[0].item_code
		)
		rows = get_latest_transition_rows_for_asn(self._asn_name)
		items = {row.asn_item for row in rows}
		self.assertEqual(len(rows), 1)
		self.assertIn(self._asn_item, items)

	def test_empty_asn_returns_empty(self):
		rows = get_latest_transition_rows_for_asn("")
		self.assertEqual(rows, [])

	def test_respects_limit(self):
		for _i in range(5):
			po = create_purchase_order(qty=1)
			asn_i = make_test_asn(purchase_order=po, qty=1)
			asn_i.insert(ignore_permissions=True)
			self._emit(
				asn=asn_i.name,
				asn_item=asn_i.items[0].name,
				item_code=asn_i.items[0].item_code,
				state="Submitted",
			)
		rows = get_latest_transition_rows_for_asn(self._asn_name, limit=3)
		self.assertLessEqual(len(rows), 3)
