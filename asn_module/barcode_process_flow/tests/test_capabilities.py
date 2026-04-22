from unittest.mock import patch

from frappe.tests import UnitTestCase

from asn_module.barcode_process_flow import capabilities


class TestCapabilities(UnitTestCase):
	def test_mr_subcontracting_capability_hidden_in_v15(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=15):
			supported = capabilities.get_supported_pairs("Material Request")
		self.assertNotIn(("Material Request", "Purchase Order", "mr_subcontracting_to_po"), supported)

	def test_mr_subcontracting_capability_available_in_v16(self):
		with patch("asn_module.barcode_process_flow.capabilities.get_erp_major", return_value=16):
			supported = capabilities.get_supported_pairs("Material Request")
		self.assertIn(("Material Request", "Purchase Order", "mr_subcontracting_to_po"), supported)
