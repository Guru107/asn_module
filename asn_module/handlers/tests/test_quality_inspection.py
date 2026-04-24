from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from asn_module.handlers.quality_inspection import on_quality_inspection_submit


class TestQualityInspectionHandlers(TestCase):
	def test_ignores_non_purchase_receipt_references(self):
		doc = SimpleNamespace(reference_type="Stock Entry", status="Accepted", name="QI-001")

		with (
			patch("asn_module.qr_engine.generate.generate_qr") as generate_qr,
			patch("asn_module.handlers.quality_inspection.attach_qr_to_doc") as attach_qr_to_doc,
		):
			on_quality_inspection_submit(doc, method="on_submit")

		generate_qr.assert_not_called()
		attach_qr_to_doc.assert_not_called()

	def test_attaches_stock_transfer_qr_for_accepted_qi(self):
		doc = SimpleNamespace(reference_type="Purchase Receipt", status="Accepted", name="QI-ACCEPTED")
		qr_result = {"image_base64": "abc", "token": "t"}

		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value=qr_result) as generate_qr,
			patch("asn_module.handlers.quality_inspection.attach_qr_to_doc") as attach_qr_to_doc,
			patch("asn_module.handlers.quality_inspection.frappe.msgprint") as msgprint,
		):
			on_quality_inspection_submit(doc, method="on_submit")

		generate_qr.assert_called_once_with(
			action="create_stock_transfer",
			source_doctype="Quality Inspection",
			source_name="QI-ACCEPTED",
		)
		attach_qr_to_doc.assert_called_once_with(doc, qr_result, "create_stock_transfer")
		msgprint.assert_called_once()

	def test_attaches_purchase_return_qr_for_rejected_qi(self):
		doc = SimpleNamespace(reference_type="Purchase Receipt", status="Rejected", name="QI-REJECTED")
		qr_result = {"image_base64": "abc", "token": "t"}

		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value=qr_result) as generate_qr,
			patch("asn_module.handlers.quality_inspection.attach_qr_to_doc") as attach_qr_to_doc,
			patch("asn_module.handlers.quality_inspection.frappe.msgprint") as msgprint,
		):
			on_quality_inspection_submit(doc, method="on_submit")

		generate_qr.assert_called_once_with(
			action="create_purchase_return",
			source_doctype="Quality Inspection",
			source_name="QI-REJECTED",
		)
		attach_qr_to_doc.assert_called_once_with(doc, qr_result, "create_purchase_return")
		msgprint.assert_called_once()

	def test_ignores_other_quality_inspection_statuses(self):
		doc = SimpleNamespace(reference_type="Purchase Receipt", status="Open", name="QI-OPEN")

		with (
			patch("asn_module.qr_engine.generate.generate_qr") as generate_qr,
			patch("asn_module.handlers.quality_inspection.attach_qr_to_doc") as attach_qr_to_doc,
			patch("asn_module.handlers.quality_inspection.frappe.msgprint") as msgprint,
		):
			on_quality_inspection_submit(doc, method="on_submit")

		generate_qr.assert_not_called()
		attach_qr_to_doc.assert_not_called()
		msgprint.assert_not_called()
