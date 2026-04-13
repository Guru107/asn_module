from hypothesis import given
from hypothesis import settings as hypothesis_settings
from frappe.tests import UnitTestCase

from asn_module.property_tests import settings as property_settings
from asn_module.property_tests.strategies import scan_text


def _identity(x):
	return x


class TestPropertyHarness(UnitTestCase):
	@given(scan_text)
	def test_property_harness_smoke_identity(self, text_value):
		self.assertEqual(_identity(text_value), text_value)
		expected_max_examples = 80 if property_settings.PROFILE == "ci" else 300
		self.assertEqual(hypothesis_settings.default.max_examples, expected_max_examples)
		self.assertIsNone(hypothesis_settings.default.deadline)
