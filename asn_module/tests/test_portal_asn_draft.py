"""A supplier draft is saved without scan codes. Submit stores the scan code label."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_ensure_item,
	create_purchase_order,
	make_test_asn,
)
from asn_module.templates.pages.asn import submit_portal_asn
from asn_module.templates.pages.asn_new import portal_draft_form
from asn_module.utils.test_setup import before_tests, build_purchase_order_with_mandatory_fields


class TestPortalAsnDraft(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		_ensure_item()

	def test_a_draft_has_no_scan_codes_until_the_supplier_submits(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Portal Draft Tax",
			qty=10,
			do_not_submit=True,
		)
		asn = make_test_asn(purchase_order=po, qty=2)
		asn.insert(ignore_permissions=True)
		asn.reload()
		self.assertEqual(asn.docstatus, 0)
		self.assertEqual(asn.status, "Draft")
		self.assertFalse(asn.scan_code_label)

		form = portal_draft_form(asn.supplier, asn.name)
		self.assertEqual(form["supplier_invoice_no"], asn.supplier_invoice_no)
		self.assertEqual(form["rows"][0]["qty"], 2)
		self.assertEqual(form["purchase_order"], po.name)

		with patch(
			"asn_module.templates.pages.asn._get_supplier_for_user",
			return_value=asn.supplier,
		):
			result = submit_portal_asn(asn.name)

		asn.reload()
		self.assertEqual(asn.docstatus, 1)
		self.assertEqual(asn.status, "Submitted")
		self.assertTrue(asn.scan_code_label)
		self.assertTrue(result["redirect"].startswith("/asn/"))
		self.assertIsNone(portal_draft_form(asn.supplier, asn.name))
