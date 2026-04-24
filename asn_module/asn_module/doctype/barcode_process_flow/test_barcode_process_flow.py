from types import SimpleNamespace
from unittest import TestCase

import frappe

from asn_module.asn_module.doctype.barcode_process_flow.barcode_process_flow import (
	BarcodeProcessFlow,
)


def _build_flow_doc(*, flow_name: str, steps: list[SimpleNamespace]) -> SimpleNamespace:
	doc = SimpleNamespace(flow_name=flow_name, steps=steps)
	doc._validate_step_uniqueness = BarcodeProcessFlow._validate_step_uniqueness.__get__(doc, type(doc))
	return doc


class TestBarcodeProcessFlowValidation(TestCase):
	def test_validate_requires_flow_name(self):
		doc = _build_flow_doc(flow_name=" ", steps=[])
		with self.assertRaises(frappe.ValidationError):
			BarcodeProcessFlow.validate(doc)

	def test_validate_trims_name_and_allows_unique_steps(self):
		doc = _build_flow_doc(
			flow_name="  Inbound  ",
			steps=[
				SimpleNamespace(
					from_doctype=" ASN ",
					to_doctype="Purchase Receipt",
					scan_action_key="create_pr",
					label="",
					name="ROW-1",
				),
				SimpleNamespace(
					from_doctype="ASN",
					to_doctype="Subcontracting Receipt",
					scan_action_key="create_subcontracting_receipt",
					label="",
					name="ROW-2",
				),
			],
		)

		BarcodeProcessFlow.validate(doc)
		self.assertEqual(doc.flow_name, "Inbound")

	def test_validate_rejects_duplicate_from_to_and_scan_action(self):
		doc = _build_flow_doc(
			flow_name="Inbound",
			steps=[
				SimpleNamespace(
					from_doctype="ASN",
					to_doctype="Purchase Receipt",
					scan_action_key="create_pr",
					label="Step A",
					name="ROW-1",
				),
				SimpleNamespace(
					from_doctype="ASN",
					to_doctype="Purchase Receipt",
					scan_action_key="create_pr",
					label="Step B",
					name="ROW-2",
				),
			],
		)

		with self.assertRaises(frappe.ValidationError):
			BarcodeProcessFlow.validate(doc)
