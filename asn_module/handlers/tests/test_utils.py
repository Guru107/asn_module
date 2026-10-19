import base64
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
from asn_module.handlers.utils import attach_qr_to_doc, fill_custom_fiscal_year
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


def _doc_with_fiscal_year_field(reqd: int = 1, **values) -> frappe._dict:
	"""A document stub whose meta carries a site-style ``custom_fiscal_year`` field."""
	doc = frappe._dict(
		doctype="Subcontracting Receipt",
		meta=SimpleNamespace(
			get_field=lambda fieldname: SimpleNamespace(reqd=reqd)
			if fieldname == "custom_fiscal_year"
			else None
		),
	)
	doc.update(values)
	return doc


class TestFillCustomFiscalYear(FrappeTestCase):
	def test_fills_a_mandatory_field_from_the_posting_date(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19")

		with patch.object(frappe.db, "get_value", return_value="_Test FY 2026-27") as get_value:
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "_Test FY 2026-27")
		get_value.assert_called_once()

	def test_falls_back_to_the_transaction_date(self):
		doc = _doc_with_fiscal_year_field(transaction_date="2026-04-05")

		with patch.object(frappe.db, "get_value", return_value="_Test FY 2026-27") as get_value:
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "_Test FY 2026-27")
		self.assertIn("2026-04-05", str(get_value.call_args))

	def test_leaves_a_doctype_without_the_field_alone(self):
		doc = _doc_with_fiscal_year_field(reqd=0, posting_date="2026-10-19")

		with patch.object(frappe.db, "get_value", side_effect=AssertionError("must not query")):
			fill_custom_fiscal_year(doc)

		self.assertNotIn("custom_fiscal_year", doc)

	def test_keeps_a_value_that_names_a_fiscal_year_the_site_has(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19", custom_fiscal_year="FY 2025-26")

		def fake_exists(doctype, name=None, *args, **kwargs):
			return name == "FY 2025-26"

		with (
			patch.object(frappe.db, "exists", side_effect=fake_exists),
			patch.object(frappe.db, "get_value", side_effect=AssertionError("must not query")),
		):
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "FY 2025-26")

	def test_replaces_a_rollover_default_that_names_a_missing_fiscal_year(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19", custom_fiscal_year="26-27")

		with (
			patch.object(frappe.db, "exists", return_value=None),
			patch.object(frappe.db, "get_value", return_value="2026-2027"),
		):
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "2026-2027")

	def test_leaves_the_field_unset_when_no_fiscal_year_covers_the_date(self):
		doc = _doc_with_fiscal_year_field(posting_date="2031-10-19")

		with patch.object(frappe.db, "get_value", return_value=None):
			fill_custom_fiscal_year(doc)

		self.assertNotIn("custom_fiscal_year", doc)
