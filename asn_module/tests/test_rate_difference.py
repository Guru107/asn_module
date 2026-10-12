import unittest

from asn_module.rate_difference import build_rate_difference_rows, rates_differ


class TestRateDifference(unittest.TestCase):
	def test_rates_differ_ignores_float_noise(self):
		self.assertFalse(rates_differ(100, 100))
		self.assertFalse(rates_differ(100.00001, 100))
		self.assertTrue(rates_differ(110, 100))

	def test_build_rows_keeps_only_lines_that_differ_and_values_the_gap(self):
		rows = build_rate_difference_rows(
			[
				{
					"asn": "ASN-0001",
					"status": "Draft",
					"supplier": "Supp-001",
					"supplier_invoice_no": "INV-1",
					"purchase_order": "PO-0001",
					"item_code": "ITEM-001",
					"asn_item": "ASN-ITEM-1",
					"asn_rate": 110,
					"po_rate": 100,
					"qty": 2,
				},
				{
					"asn": "ASN-0002",
					"status": "Submitted",
					"supplier": "Supp-001",
					"supplier_invoice_no": "INV-2",
					"purchase_order": "PO-0002",
					"item_code": "ITEM-002",
					"asn_item": "ASN-ITEM-2",
					"asn_rate": 50,
					"po_rate": 50,
					"qty": 4,
				},
			]
		)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["asn"], "ASN-0001")
		self.assertEqual(rows[0]["asn_rate"], 110.0)
		self.assertEqual(rows[0]["po_rate"], 100.0)
		# 110 - 100 = 10; 2 x 10 = 20 for settlement
		self.assertEqual(rows[0]["rate_difference"], 10.0)
		self.assertEqual(rows[0]["amount_difference"], 20.0)

	def test_lower_asn_rate_is_a_negative_difference(self):
		rows = build_rate_difference_rows(
			[
				{
					"asn": "ASN-0003",
					"status": "Submitted",
					"supplier": "Supp-001",
					"supplier_invoice_no": "INV-3",
					"purchase_order": "PO-0003",
					"item_code": "ITEM-003",
					"asn_item": "ASN-ITEM-3",
					"asn_rate": 80,
					"po_rate": 100,
					"qty": 3,
				}
			]
		)
		self.assertEqual(rows[0]["rate_difference"], -20.0)
		self.assertEqual(rows[0]["amount_difference"], -60.0)
