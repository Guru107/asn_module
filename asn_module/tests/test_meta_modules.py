from unittest import TestCase

from asn_module.property_tests import property_suite
from asn_module.tests import compat


class TestMetaModules(TestCase):
	def test_property_suite_exports_property_test_classes(self):
		self.assertEqual(
			property_suite.__all__,
			[
				"TestBarcodeProcessFlowProperties",
				"TestPropertyHarness",
				"TestScanCodeProperties",
				"TestTokenProperties",
			],
		)

	def test_compat_exports_unit_test_case_alias(self):
		self.assertIn("UnitTestCase", compat.__all__)
		self.assertIsNotNone(compat.UnitTestCase)
