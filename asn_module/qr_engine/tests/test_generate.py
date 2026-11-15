from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase as UnitTestCase

from asn_module.qr_engine.generate import (
	InvalidScanImageRequest,
	scan_image,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CODE = "ABCDEFGH23456789"


class TestScanImageEndpoint(UnitTestCase):
	def test_canonical_code_returns_png_for_each_kind_with_immutable_cache(self):
		for kind in ("barcode", "qr"):
			response = scan_image(code=CODE, kind=kind)

			self.assertEqual(response.mimetype, "image/png")
			self.assertTrue(response.data.startswith(PNG_MAGIC))
			self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")

	def test_malformed_code_or_unknown_kind_is_a_400(self):
		for code, kind in (
			("SHORT", "qr"),
			("0000000000000000", "barcode"),
			(None, "qr"),
			(CODE, "gif"),
			(CODE, None),
		):
			with self.assertRaises(InvalidScanImageRequest) as ctx:
				scan_image(code=code, kind=kind)
			self.assertEqual(ctx.exception.http_status_code, 400)

	def test_endpoint_is_guest_whitelisted(self):
		self.assertIn(scan_image, frappe.guest_methods)

	def test_endpoint_is_rate_limited_at_120_requests_per_minute_per_ip(self):
		# rate_limit is a no-op without a request, so fake one; the cache is callable (v15) or not (v16).
		cache = MagicMock()
		cache.return_value = cache
		cache.get.return_value = None
		with (
			patch.object(frappe, "request", MagicMock(), create=True),
			patch.object(frappe.local, "request_ip", "10.0.0.1", create=True),
			patch.object(frappe, "cache", cache),
		):
			cache.incrby.return_value = 120
			self.assertEqual(scan_image(code=CODE, kind="qr").mimetype, "image/png")

			cache.incrby.return_value = 121
			with self.assertRaises(frappe.RateLimitExceededError):
				scan_image(code=CODE, kind="qr")

		self.assertEqual(cache.setex.call_args.args[1], 60)

	def test_endpoint_does_no_database_access_and_needs_no_registry_row(self):
		# spec=[] makes any frappe.db attribute access raise.
		with patch("asn_module.qr_engine.generate.frappe.db", MagicMock(spec=[])):
			response = scan_image(code=CODE, kind="barcode")
			scan_image(code=CODE, kind="qr")

		self.assertTrue(response.data.startswith(PNG_MAGIC))

	def test_qr_encodes_the_scan_station_url_for_the_code(self):
		with (
			patch("asn_module.qr_engine.generate.frappe.utils.get_url", return_value="https://example.com"),
			patch("asn_module.qr_engine.generate.pyqrcode.create") as create_qr,
		):
			create_qr.return_value.png.side_effect = lambda buffer, scale: buffer.write(PNG_MAGIC)
			scan_image(code=CODE, kind="qr")

		create_qr.assert_called_once_with(f"https://example.com/app/scan-station?code={CODE}")

	def test_qr_trims_a_trailing_slash_from_the_site_url(self):
		with (
			patch("asn_module.qr_engine.generate.frappe.utils.get_url", return_value="https://example.com/"),
			patch("asn_module.qr_engine.generate.pyqrcode.create") as create_qr,
		):
			create_qr.return_value.png.side_effect = lambda buffer, scale: buffer.write(PNG_MAGIC)
			scan_image(code=CODE, kind="qr")

		create_qr.assert_called_once_with(f"https://example.com/app/scan-station?code={CODE}")

	def test_barcode_falls_back_to_default_options_on_type_error(self):
		writer = MagicMock()
		writer.write.side_effect = [TypeError("options unsupported"), None]
		with patch("asn_module.qr_engine.generate.barcode") as mock_barcode:
			mock_barcode.get.return_value = writer
			response = scan_image(code=CODE, kind="barcode")

		self.assertEqual(writer.write.call_count, 2)
		self.assertNotIn("options", writer.write.call_args_list[1].kwargs)
		self.assertEqual(response.mimetype, "image/png")

	def test_barcode_keeps_its_human_readable_label(self):
		with patch("asn_module.qr_engine.generate.barcode") as mock_barcode:
			mock_barcode.get.return_value.write.side_effect = lambda buffer, options=None: buffer.write(
				PNG_MAGIC
			)
			scan_image(code=CODE.lower(), kind="barcode")

		self.assertEqual(mock_barcode.get.call_args.args[:2], ("code128", CODE))
