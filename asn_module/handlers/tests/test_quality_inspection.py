from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.handlers.quality_inspection import on_quality_inspection_submit


class TestQualityInspectionSubmitHook(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_purchase_receipt(self, submit=False):
		purchase_order = create_purchase_order(
			transaction_date="2026-03-30",
			schedule_date="2026-03-31",
			item_schedule_date="2026-03-31",
		)
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
		if submit:
			pr.submit()
		return pr

	def _make_quality_inspection(self, reference_type, reference_name, item_code, status):
		return frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": reference_type,
				"reference_name": reference_name,
				"item_code": item_code,
				"sample_size": 4,
				"status": status,
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
			}
		)

	@patch("asn_module.handlers.quality_inspection._attach_qr_to_doc")
	@patch("asn_module.handlers.quality_inspection.frappe.msgprint")
	@patch("asn_module.qr_engine.generate.generate_qr")
	def test_accepted_quality_inspection_generates_stock_transfer_qr(
		self,
		generate_qr,
		msgprint,
		attach_qr_to_doc,
	):
		pr = self._make_purchase_receipt(submit=True)
		qi = self._make_quality_inspection("Purchase Receipt", pr.name, pr.items[0].item_code, "Accepted")

		generate_qr.return_value = {"image_base64": "ZmFrZS1xcg=="}

		on_quality_inspection_submit(qi, "on_submit")

		self.assertEqual(generate_qr.call_count, 1)
		self.assertEqual(generate_qr.call_args.kwargs["action"], "create_stock_transfer")
		self.assertEqual(generate_qr.call_args.kwargs["source_doctype"], "Quality Inspection")
		self.assertEqual(generate_qr.call_args.kwargs["source_name"], qi.name)
		attach_qr_to_doc.assert_called_once()
		msgprint.assert_called_once()

	@patch("asn_module.handlers.quality_inspection._attach_qr_to_doc")
	@patch("asn_module.handlers.quality_inspection.frappe.msgprint")
	@patch("asn_module.qr_engine.generate.generate_qr")
	def test_rejected_quality_inspection_generates_purchase_return_qr(
		self,
		generate_qr,
		msgprint,
		attach_qr_to_doc,
	):
		pr = self._make_purchase_receipt(submit=True)
		qi = self._make_quality_inspection("Purchase Receipt", pr.name, pr.items[0].item_code, "Rejected")

		generate_qr.return_value = {"image_base64": "ZmFrZS1xcg=="}

		on_quality_inspection_submit(qi, "on_submit")

		self.assertEqual(generate_qr.call_count, 1)
		self.assertEqual(generate_qr.call_args.kwargs["action"], "create_purchase_return")
		self.assertEqual(generate_qr.call_args.kwargs["source_doctype"], "Quality Inspection")
		self.assertEqual(generate_qr.call_args.kwargs["source_name"], qi.name)
		attach_qr_to_doc.assert_called_once()
		msgprint.assert_called_once()

	@patch("asn_module.handlers.quality_inspection._attach_qr_to_doc")
	@patch("asn_module.handlers.quality_inspection.frappe.msgprint")
	@patch("asn_module.qr_engine.generate.generate_qr")
	def test_ignores_non_purchase_receipt_quality_inspection(
		self,
		generate_qr,
		msgprint,
		attach_qr_to_doc,
	):
		purchase_order = create_purchase_order(
			transaction_date="2026-03-30",
			schedule_date="2026-03-31",
			item_schedule_date="2026-03-31",
		)
		qi = self._make_quality_inspection(
			"Purchase Order",
			purchase_order.name,
			purchase_order.items[0].item_code,
			"Accepted",
		)

		on_quality_inspection_submit(qi, "on_submit")

		generate_qr.assert_not_called()
		attach_qr_to_doc.assert_not_called()
		msgprint.assert_not_called()

	@patch("asn_module.handlers.quality_inspection._attach_qr_to_doc")
	@patch("asn_module.handlers.quality_inspection.frappe.msgprint")
	@patch("asn_module.qr_engine.generate.generate_qr")
	def test_ignores_draft_purchase_receipt_reference(
		self,
		generate_qr,
		msgprint,
		attach_qr_to_doc,
	):
		pr = self._make_purchase_receipt(submit=False)
		qi = self._make_quality_inspection("Purchase Receipt", pr.name, pr.items[0].item_code, "Accepted")

		on_quality_inspection_submit(qi, "on_submit")

		generate_qr.assert_not_called()
		attach_qr_to_doc.assert_not_called()
		msgprint.assert_not_called()
