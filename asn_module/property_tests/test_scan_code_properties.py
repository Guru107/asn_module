from frappe.tests.utils import FrappeTestCase as UnitTestCase
from hypothesis import given

from asn_module.property_tests.strategies import scan_text
from asn_module.qr_engine.scan_codes import normalize_scan_code


class TestScanCodeProperties(UnitTestCase):
	@given(scan_text)
	def test_normalize_scan_code_is_idempotent(self, raw_code):
		once = normalize_scan_code(raw_code)
		twice = normalize_scan_code(once)
		self.assertEqual(once, twice)
