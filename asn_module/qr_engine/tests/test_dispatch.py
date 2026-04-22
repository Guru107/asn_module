from types import SimpleNamespace
from unittest.mock import patch

from asn_module.qr_engine.dispatch import ScanCodeNotFoundError, dispatch
from asn_module.tests.compat import UnitTestCase


class TestDispatch(UnitTestCase):
	def test_dispatch_success_uses_flow_step_runtime(self):
		scan_doc = SimpleNamespace(
			name="CODE123",
			action_key="STEP-INBOUND",
			source_doctype="ASN",
			source_name="ASN-0001",
		)
		source_doc = SimpleNamespace(doctype="ASN", name="ASN-0001")
		matched = [
			SimpleNamespace(flow_label="Inbound", step_name="STEP-0001", label="ASN -> Purchase Receipt")
		]
		runtime_result = {
			"doctype": "Purchase Receipt",
			"name": "MAT-PRE-0001",
			"url": "/app/purchase-receipt/MAT-PRE-0001",
			"message": "created",
		}

		with (
			patch("asn_module.qr_engine.dispatch.normalize_scan_code", return_value="CODE123"),
			patch("asn_module.qr_engine.dispatch.get_scan_code_doc", return_value=scan_doc),
			patch("asn_module.qr_engine.dispatch.validate_scan_code_row"),
			patch("asn_module.qr_engine.dispatch.frappe.get_doc", return_value=source_doc),
			patch(
				"asn_module.qr_engine.dispatch.dispatch_from_scan",
				return_value=(runtime_result, matched),
			),
			patch("asn_module.qr_engine.dispatch.record_successful_scan"),
			patch("asn_module.qr_engine.dispatch._log_scan"),
		):
			result = dispatch(code="CODE123", device_info="Scanner-1")

		self.assertTrue(result["success"])
		self.assertEqual(result["action"], "STEP-INBOUND")
		self.assertEqual(result["flow_name"], "Inbound")
		self.assertEqual(result["step_name"], "STEP-0001")
		self.assertEqual(result["doctype"], "Purchase Receipt")

	def test_dispatch_missing_scan_code_raises(self):
		with self.assertRaises(ScanCodeNotFoundError):
			dispatch(code=None)

	def test_dispatch_unknown_scan_code_raises(self):
		with patch("asn_module.qr_engine.dispatch.normalize_scan_code", return_value="CODE123"):
			with patch("asn_module.qr_engine.dispatch.get_scan_code_doc", return_value=None):
				with self.assertRaises(ScanCodeNotFoundError):
					dispatch(code="CODE123")
