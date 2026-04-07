import base64

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.handlers.utils import attach_qr_to_doc
from asn_module.utils.test_setup import before_tests


class TestAttachQrToDoc(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		po = create_purchase_order(qty=10)
		cls._asn = make_test_asn(purchase_order=po, qty=10)
		cls._asn.insert(ignore_permissions=True)

	def test_creates_file_attached_to_target(self):
		# PNG magic header only — attach_qr_to_doc saves the base64 bytes without
		# validating image content, so a minimal header is sufficient for testing.
		minimal_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
		qr_result = {"image_base64": minimal_png}
		attach_qr_to_doc(self._asn, qr_result, "qr")

		files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "ASN",
				"attached_to_name": self._asn.name,
			},
			fields=["name", "file_name"],
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0]["file_name"].startswith("qr-"))

	def test_invalid_base64_raises_error(self):
		with self.assertRaises(Exception):
			attach_qr_to_doc(self._asn, {"image_base64": "not-valid-base64!!!"}, "qr")

	def test_missing_image_base64_raises_key_error(self):
		with self.assertRaises(KeyError):
			attach_qr_to_doc(self._asn, {}, "qr")
