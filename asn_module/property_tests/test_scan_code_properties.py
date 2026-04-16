from frappe.tests import UnitTestCase
from hypothesis import given

from asn_module.property_tests.strategies import scan_text
from asn_module.qr_engine.scan_codes import format_scan_code_for_display, normalize_scan_code


class TestScanCodeProperties(UnitTestCase):
	@given(scan_text)
	def test_normalize_scan_code_is_idempotent(self, raw_code):
		once = normalize_scan_code(raw_code)
		twice = normalize_scan_code(once)
		self.assertEqual(once, twice)

	@given(scan_text)
	def test_format_scan_code_for_display_preserves_normalized_content(self, raw_code):
		normalized = normalize_scan_code(raw_code)
		display = format_scan_code_for_display(raw_code)
		self.assertEqual(display.replace("-", ""), normalized)
		if display:
			self.assertEqual(display, display.upper())
			self.assertNotIn(" ", display)
			for chunk in display.split("-"):
				self.assertLessEqual(len(chunk), 4)
