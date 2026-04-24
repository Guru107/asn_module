from unittest.mock import patch

import frappe

from asn_module.qr_engine.generate import build_scan_code_metadata, generate_barcode, generate_qr
from asn_module.tests.compat import UnitTestCase


class TestGenerate(UnitTestCase):
	def _generate_qr(self, site_url):
		def write_png(buffer, scale):
			buffer.write(b"fake-qr-image")

		with (
			patch("asn_module.qr_engine.generate.get_or_create_scan_code", return_value="FIXEDCODE123"),
			patch("asn_module.qr_engine.generate.frappe.utils.get_url", return_value=site_url),
			patch("asn_module.qr_engine.generate.pyqrcode.create") as create_qr,
		):
			create_qr.return_value.png.side_effect = write_png
			return generate_qr(
				action="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
			)

	def test_generate_qr_returns_expected_contract(self):
		result = self._generate_qr("https://example.com")

		self.assertEqual(result["scan_code"], "FIXEDCODE123")
		self.assertIn("human_readable", result)
		self.assertIn("url", result)
		self.assertIn("image_base64", result)
		self.assertEqual(
			result["url"],
			"https://example.com/api/method/asn_module.qr_engine.dispatch.dispatch?code=FIXEDCODE123",
		)
		self.assertTrue(result["image_base64"])

	def test_generate_qr_trims_trailing_slash_from_site_url(self):
		result = self._generate_qr("https://example.com/")

		self.assertEqual(
			result["url"],
			"https://example.com/api/method/asn_module.qr_engine.dispatch.dispatch?code=FIXEDCODE123",
		)

	def test_generate_barcode_returns_expected_contract(self):
		with patch("asn_module.qr_engine.generate.get_or_create_scan_code", return_value="FIXEDCODE123"):
			result = generate_barcode(
				action="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
			)

		self.assertEqual(result["scan_code"], "FIXEDCODE123")
		self.assertIn("human_readable", result)
		self.assertIn("image_base64", result)
		self.assertTrue(result["image_base64"])

	def test_generate_barcode_falls_back_on_type_error(self):
		"""If barcode writer raises TypeError on options, try without options."""
		import io

		with patch("asn_module.qr_engine.generate.get_or_create_scan_code", return_value="FIXEDCODE123"):
			with patch("asn_module.qr_engine.generate.barcode") as mock_barcode:
				mock_code = mock_barcode.get.return_value
				mock_code.writer.return_value = mock_barcode.get.return_value.writer.return_value
				mock_code.write.side_effect = [TypeError("bad options"), None]
				result = generate_barcode(
					action="create_purchase_receipt",
					source_doctype="ASN",
					source_name="ASN-00001",
				)
				self.assertEqual(result["scan_code"], "FIXEDCODE123")

	def test_build_scan_code_metadata_rejects_invalid_generation_mode(self):
		with self.assertRaises(frappe.ValidationError):
			build_scan_code_metadata(
				action_key="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
				generation_mode="later",
			)

	def test_build_scan_code_metadata_normalizes_generation_mode(self):
		with patch("asn_module.qr_engine.generate.get_or_create_scan_code", return_value="FIXEDCODE123"):
			result = build_scan_code_metadata(
				action_key="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
				generation_mode=" Hybrid ",
			)
		self.assertEqual(result["generation_mode"], "hybrid")
