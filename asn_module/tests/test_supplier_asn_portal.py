from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from asn_module.supplier_asn_portal import (
	asn_eligible_for_supplier_portal_cancel,
	purchase_receipt_exists_for_asn,
)


class TestSupplierAsnPortal(FrappeTestCase):
	def test_purchase_receipt_exists_for_asn(self):
		with patch("frappe.db.exists", return_value="PR-0001"):
			self.assertTrue(purchase_receipt_exists_for_asn("ASN-0001"))
		with patch("frappe.db.exists", return_value=None):
			self.assertFalse(purchase_receipt_exists_for_asn("ASN-0001"))

	def test_asn_eligible_for_supplier_portal_cancel(self):
		doc = SimpleNamespace(docstatus=1, status="Submitted", name="ASN-1")
		with patch(
			"asn_module.supplier_asn_portal.purchase_receipt_exists_for_asn",
			return_value=False,
		):
			self.assertTrue(asn_eligible_for_supplier_portal_cancel(doc))
		with patch(
			"asn_module.supplier_asn_portal.purchase_receipt_exists_for_asn",
			return_value=True,
		):
			self.assertFalse(asn_eligible_for_supplier_portal_cancel(doc))

		draft = SimpleNamespace(docstatus=0, status="Draft", name="ASN-2")
		with patch(
			"asn_module.supplier_asn_portal.purchase_receipt_exists_for_asn",
			return_value=False,
		):
			self.assertFalse(asn_eligible_for_supplier_portal_cancel(draft))

		partial = SimpleNamespace(docstatus=1, status="Partially Received", name="ASN-3")
		with patch(
			"asn_module.supplier_asn_portal.purchase_receipt_exists_for_asn",
			return_value=False,
		):
			self.assertFalse(asn_eligible_for_supplier_portal_cancel(partial))
