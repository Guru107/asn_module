from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow import capabilities
from asn_module.tests.compat import UnitTestCase


class TestCapabilities(UnitTestCase):
	def test_mr_subcontracting_capability_hidden_in_v15(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=15):
			supported = capabilities.get_supported_pairs("Material Request")
		self.assertNotIn(("Material Request", "Purchase Order", "mr_subcontracting_to_po"), supported)

	def test_mr_subcontracting_capability_available_in_v16(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=16):
			supported = capabilities.get_supported_pairs("Material Request")
		self.assertIn(("Material Request", "Purchase Order", "mr_subcontracting_to_po"), supported)

	def test_get_supported_templates_filters_by_source_and_version(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=15):
			templates = capabilities.get_supported_templates(from_doctype="Material Request")
		self.assertTrue(all(row["from_doctype"] == "Material Request" for row in templates))
		self.assertNotIn("mr_subcontracting_to_po", [row["key"] for row in templates])

	def test_get_standard_handler_respects_doc_conditions(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=16):
			source_doc = SimpleNamespace(material_request_type="Subcontracting")
			handler = capabilities.get_standard_handler(
				from_doctype="Material Request",
				to_doctype="Purchase Order",
				source_doc=source_doc,
			)
		self.assertEqual(
			handler,
			"asn_module.barcode_process_flow.handlers.material_request_to_purchase_order",
		)

	def test_get_standard_handler_returns_none_when_conditions_fail(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=16):
			source_doc = SimpleNamespace(material_request_type="Purchase")
			handler = capabilities.get_standard_handler(
				from_doctype="Material Request",
				to_doctype="Work Order",
				source_doc=source_doc,
			)
		self.assertIsNone(handler)

	def test_version_and_condition_helpers(self):
		self.assertTrue(capabilities._is_version_supported({"min_erp_major": 15, "max_erp_major": 16}, 16))
		self.assertFalse(capabilities._is_version_supported({"min_erp_major": 17}, 16))
		self.assertTrue(capabilities._doc_matches_conditions(SimpleNamespace(kind="A"), {"kind": ["A", "B"]}))
		self.assertFalse(
			capabilities._doc_matches_conditions(SimpleNamespace(kind="C"), {"kind": ["A", "B"]})
		)

	def test_get_erp_major_fallback_and_invalid_version(self):
		capabilities.get_erp_major.cache_clear()
		with (
			patch(
				"asn_module.barcode_process_flow.capabilities.import_module",
				side_effect=Exception("no erpnext"),
			),
			patch("asn_module.barcode_process_flow.capabilities.frappe.get_attr", return_value="16.2.1"),
		):
			self.assertEqual(capabilities.get_erp_major(), 16)

		capabilities.get_erp_major.cache_clear()
		with patch(
			"asn_module.barcode_process_flow.capabilities.import_module",
			return_value=SimpleNamespace(__version__="beta"),
		):
			self.assertEqual(capabilities.get_erp_major(), 0)
