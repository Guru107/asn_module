from unittest.mock import patch

from frappe.tests import UnitTestCase

from asn_module.qr_engine.generate import generate_barcode, generate_qr


class TestGenerate(UnitTestCase):
	def _generate_qr(self, site_url):
		def write_png(buffer, scale):
			buffer.write(b"fake-qr-image")

		with (
			patch("asn_module.qr_engine.generate.create_token", return_value="fixed-token"),
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

		self.assertEqual(result["token"], "fixed-token")
		self.assertIn("url", result)
		self.assertIn("image_base64", result)
		self.assertEqual(
			result["url"],
			"https://example.com/api/method/asn_module.qr_engine.dispatch.dispatch?token=fixed-token",
		)
		self.assertTrue(result["image_base64"])

	def test_generate_qr_trims_trailing_slash_from_site_url(self):
		result = self._generate_qr("https://example.com/")

		self.assertEqual(
			result["url"],
			"https://example.com/api/method/asn_module.qr_engine.dispatch.dispatch?token=fixed-token",
		)

	def test_generate_barcode_returns_expected_contract(self):
		with patch("asn_module.qr_engine.generate.create_token", return_value="fixed-token"):
			result = generate_barcode(
				action="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
			)

		self.assertEqual(result["token"], "fixed-token")
		self.assertIn("image_base64", result)
		self.assertTrue(result["image_base64"])
