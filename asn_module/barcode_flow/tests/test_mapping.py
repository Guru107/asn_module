import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

frappe_stub = sys.modules.get("frappe")
if frappe_stub is None:
	frappe_stub = ModuleType("frappe")
	sys.modules["frappe"] = frappe_stub
if not hasattr(frappe_stub, "ValidationError"):
	frappe_stub.ValidationError = type("ValidationError", (Exception,), {})
if not hasattr(frappe_stub, "get_doc"):
	frappe_stub.get_doc = lambda payload: payload

from asn_module.barcode_flow.mapping import build_target_doc


class TestBarcodeFlowMapping(TestCase):
	def test_build_target_doc_maps_source_fields_from_dict_source(self):
		source_doc = {
			"header": {
				"set_warehouse": "WH-001",
				"supplier": "SUP-001",
			}
		}
		mappings = [
			SimpleNamespace(
				mapping_type="source",
				source_field_path="header.set_warehouse",
				target_field_path="target.set_warehouse",
			),
			SimpleNamespace(
				mapping_type="source",
				source_field_path="header.supplier",
				target_field_path="supplier",
			),
		]

		with patch("asn_module.barcode_flow.mapping.frappe.get_doc", side_effect=lambda payload: payload):
			payload = build_target_doc(source_doc=source_doc, mappings=mappings, target_doctype="Purchase Receipt")

		self.assertEqual(payload["doctype"], "Purchase Receipt")
		self.assertEqual(payload["set_warehouse"], "WH-001")
		self.assertEqual(payload["supplier"], "SUP-001")

	def test_build_target_doc_applies_constant_mappings(self):
		source_doc = SimpleNamespace(company="COMP-001")
		mappings = [
			SimpleNamespace(
				mapping_type="constant",
				target_field_path="target.set_warehouse",
				constant_value="WH-CONSTANT",
			),
			SimpleNamespace(
				mapping_type="source",
				source_field_path="company",
				target_field_path="company",
			),
		]

		with patch("asn_module.barcode_flow.mapping.frappe.get_doc", side_effect=lambda payload: payload):
			payload = build_target_doc(source_doc=source_doc, mappings=mappings, target_doctype="Purchase Receipt")

		self.assertEqual(payload["set_warehouse"], "WH-CONSTANT")
		self.assertEqual(payload["company"], "COMP-001")
