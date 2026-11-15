import frappe
from frappe.tests.utils import FrappeTestCase

INDEXED_FIELDS = {
	"ASN": ("supplier", "supplier_invoice_no", "status"),
	"ASN Item": ("purchase_order",),
	"Purchase Receipt": ("asn",),
}


class TestSearchIndexes(FrappeTestCase):
	def test_hot_path_filters_are_indexed(self):
		for doctype, fieldnames in INDEXED_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				self.assertTrue(meta.get_field(fieldname).search_index, f"{doctype}.{fieldname}")
