import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.traceability import (
	_idempotency_key,
	emit_asn_item_transition,
	get_latest_transition_rows_for_asn,
)


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


class TestEmitAsnItemTransition(FrappeTestCase):
	def test_creates_row(self):
		asn = f"ASN-TR-{frappe.generate_hash(length=6)}"
		name = emit_asn_item_transition(
			asn=asn,
			asn_item="ASN-ITEM-001",
			item_code="ITEM-001",
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-001",
		)
		self.assertTrue(name)
		doc = frappe.get_doc("ASN Transition Log", name)
		self.assertEqual(doc.asn, asn)
		self.assertEqual(doc.state, "Received")

	def test_deduplicates_on_replay(self):
		asn = f"ASN-TR-D-{frappe.generate_hash(length=6)}"
		first = emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			ref_doctype="ASN",
			ref_name=asn,
		)
		second = emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			ref_doctype="ASN",
			ref_name=asn,
		)
		self.assertIsNotNone(first)
		self.assertIsNone(second)

	def test_returns_none_on_empty_asn(self):
		result = emit_asn_item_transition(asn="", state="Submitted")
		self.assertIsNone(result)

	def test_different_ref_name_same_state_creates_new_row(self):
		asn = f"ASN-TR-RN-{frappe.generate_hash(length=6)}"
		first = emit_asn_item_transition(
			asn=asn,
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-001",
		)
		second = emit_asn_item_transition(
			asn=asn,
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-002",
		)
		self.assertIsNotNone(first)
		self.assertIsNotNone(second)
		self.assertNotEqual(first, second)


class TestGetLatestTransitionRowsForAsn(FrappeTestCase):
	def test_returns_latest_per_item(self):
		asn = f"ASN-LT-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-1",
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-1",
			state="Received",
		)
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-2",
			state="Submitted",
		)
		rows = get_latest_transition_rows_for_asn(asn)
		items = {row.asn_item for row in rows}
		self.assertEqual(len(rows), 2)
		self.assertIn("ITEM-1", items)
		self.assertIn("ITEM-2", items)

	def test_empty_asn_returns_empty(self):
		rows = get_latest_transition_rows_for_asn("")
		self.assertEqual(rows, [])

	def test_respects_limit(self):
		asn = f"ASN-LTL-{frappe.generate_hash(length=6)}"
		for i in range(5):
			emit_asn_item_transition(
				asn=asn,
				asn_item=f"LIMIT-ITEM-{i}",
				state="Submitted",
			)
		rows = get_latest_transition_rows_for_asn(asn, limit=3)
		self.assertLessEqual(len(rows), 3)
