from hypothesis import given

from asn_module.property_tests.strategies import scan_text
from asn_module.qr_engine.scan_codes import format_scan_code_for_display, normalize_scan_code
from asn_module.tests.compat import UnitTestCase


class TestScanCodeProperties(UnitTestCase):
	@given(scan_text)
	def test_normalize_scan_code_is_idempotent(self, raw_code):
		once = normalize_scan_code(raw_code)
		twice = normalize_scan_code(once)
		self.assertEqual(once, twice)

	@given(scan_text)
	def test_format_scan_code_for_display_returns_plain_uppercase_without_separators(self, raw_code):
		display = format_scan_code_for_display(raw_code)
		if display:
			self.assertEqual(display, display.upper())
			self.assertNotIn(" ", display)
			self.assertNotIn("-", display)
		self.assertEqual(display, raw_code.replace("-", "").replace(" ", "").upper())
