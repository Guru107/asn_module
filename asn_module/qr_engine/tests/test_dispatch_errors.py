from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import UnitTestCase

from asn_module.qr_engine.dispatch import dispatch


class TestDispatchErrors(UnitTestCase):
	def test_dispatch_logs_failure_when_runtime_throws(self):
		scan_doc = SimpleNamespace(
			name="CODE123",
			action_key="STEP-INBOUND",
			source_doctype="ASN",
			source_name="ASN-0001",
		)
		source_doc = SimpleNamespace(doctype="ASN", name="ASN-0001")

		with (
			patch("asn_module.qr_engine.dispatch.normalize_scan_code", return_value="CODE123"),
			patch("asn_module.qr_engine.dispatch.get_scan_code_doc", return_value=scan_doc),
			patch("asn_module.qr_engine.dispatch.validate_scan_code_row"),
			patch("asn_module.qr_engine.dispatch.frappe.get_doc", return_value=source_doc),
			patch("asn_module.qr_engine.dispatch.dispatch_from_scan", side_effect=RuntimeError("boom")),
			patch("asn_module.qr_engine.dispatch._log_scan") as log_scan,
			patch("asn_module.qr_engine.dispatch.frappe.db.commit") as db_commit,
		):
			with self.assertRaises(RuntimeError):
				dispatch(code="CODE123")

		log_scan.assert_called_once()
		db_commit.assert_called_once()
