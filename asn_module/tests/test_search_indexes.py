import frappe

from asn_module.tests.compat import IntegrationTestCase

INDEXED_FIELDS = {
	"ASN": ("supplier", "supplier_invoice_no", "status"),
	"ASN Item": ("purchase_order",),
	"Purchase Receipt": ("asn",),
	"Purchase Invoice": ("asn",),
}


class TestSearchIndexes(IntegrationTestCase):
	def test_hot_path_filters_are_indexed(self):
		for doctype, fieldnames in INDEXED_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				self.assertTrue(meta.get_field(fieldname).search_index, f"{doctype}.{fieldname}")
