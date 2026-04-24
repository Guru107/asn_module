import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	before_tests,
	create_purchase_order_with_fiscal_dates,
)
from asn_module.handlers.putaway import confirm_putaway


class TestConfirmPutaway(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_draft_purchase_receipt(self):
		purchase_order = create_purchase_order_with_fiscal_dates()
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": purchase_order.supplier,
				"company": purchase_order.company,
				"items": [
					{
						"item_code": purchase_order.items[0].item_code,
						"qty": 1,
						"rate": purchase_order.items[0].rate,
						"purchase_order": purchase_order.name,
						"purchase_order_item": purchase_order.items[0].name,
						"warehouse": purchase_order.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		return pr

	def test_creates_scan_log_for_putaway(self):
		pr = self._make_draft_purchase_receipt()

		result = confirm_putaway(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={
				"action": "confirm_putaway",
				"source_doctype": "Purchase Receipt",
				"source_name": pr.name,
				"device_info": "Ignored-For-Putaway-Spec",
			},
		)

		self.assertEqual(result["doctype"], "Scan Log")
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.action, "confirm_putaway")
		self.assertEqual(log.result, "Success")
		self.assertEqual(log.device_info, "Desktop")

	def test_putaway_rejects_missing_source_document(self):
		missing_name = f"PR-MISSING-{frappe.generate_hash(length=10)}"
		with self.assertRaises(frappe.ValidationError):
			confirm_putaway("Purchase Receipt", missing_name, payload={})

	def test_putaway_rejects_invalid_source_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			confirm_putaway("DoesNotExistDocType", "DOC-001", payload={})

	def test_putaway_emits_asn_item_transition_when_mapping_exists(self):
		pr = SimpleNamespace(
			name="MAT-PRE-TEST-0001",
			asn="ASN-0001",
			asn_items=json.dumps({"1": {"asn_item_name": "ASN-ITEM-0001"}}),
			items=[SimpleNamespace(idx=1, item_code="ITEM-1")],
		)
		log_doc = SimpleNamespace(name="SLG-0001")
		log_doc.insert = lambda **kwargs: log_doc

		def fake_get_doc(arg1, arg2=None):
			if arg1 == "Purchase Receipt":
				return pr
			if isinstance(arg1, dict) and arg1.get("doctype") == "Scan Log":
				return log_doc
			raise AssertionError(f"Unexpected get_doc call: {arg1}, {arg2}")

		def fake_exists(doctype, name=None):
			if doctype == "DocType" and name == "Purchase Receipt":
				return True
			if doctype == "Purchase Receipt" and name == "MAT-PRE-TEST-0001":
				return True
			return False

		with (
			patch("asn_module.handlers.putaway.frappe.db.exists", side_effect=fake_exists),
			patch("asn_module.handlers.putaway.frappe.get_doc", side_effect=fake_get_doc),
			patch("asn_module.handlers.putaway.emit_asn_item_transition") as emit_transition,
		):
			confirm_putaway(
				source_doctype="Purchase Receipt",
				source_name="MAT-PRE-TEST-0001",
				payload={},
			)

		emit_transition.assert_called_once_with(
			asn="ASN-0001",
			asn_item="ASN-ITEM-0001",
			item_code="ITEM-1",
			state="PUTAWAY_CONFIRMED",
			transition_status="OK",
			ref_doctype="Purchase Receipt",
			ref_name="MAT-PRE-TEST-0001",
		)
