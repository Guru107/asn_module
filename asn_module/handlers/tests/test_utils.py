import base64

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.handlers.utils import attach_qr_to_doc


class TestAttachQrToDoc(FrappeTestCase):
	def test_creates_file_attached_to_target(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": "ATT-TEST-" + frappe.generate_hash(length=6),
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		minimal_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
		qr_result = {"image_base64": minimal_png}
		attach_qr_to_doc(asn, qr_result, "qr")

		files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "ASN",
				"attached_to_name": asn.name,
			},
			fields=["name", "file_name"],
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0]["file_name"].startswith("qr-"))

	def test_invalid_base64_raises_error(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": "ATT-BAD-" + frappe.generate_hash(length=6),
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		with self.assertRaises(Exception):
			attach_qr_to_doc(asn, {"image_base64": "not-valid-base64!!!"}, "qr")

	def test_missing_image_base64_raises_key_error(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": "ATT-NOKEY-" + frappe.generate_hash(length=6),
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		with self.assertRaises(KeyError):
			attach_qr_to_doc(asn, {}, "qr")
