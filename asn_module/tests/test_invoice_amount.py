import unittest

from asn_module.invoice_amount import (
	applied_tax_percent,
	header_tax_percent_from_charges,
	invoice_amount_for_lines,
	item_tax_percents,
	line_invoice_amount,
)


class TestInvoiceAmount(unittest.TestCase):
	def test_item_tax_percents_sum_account_heads(self):
		self.assertEqual(item_tax_percents('{"CGST": 9, "SGST": 9}'), [9.0, 9.0])

	def test_item_tax_percents_ignore_blank_and_invalid_json(self):
		self.assertEqual(item_tax_percents(""), [])
		self.assertEqual(item_tax_percents("not-json"), [])
		self.assertEqual(item_tax_percents(None), [])

	def test_header_tax_uses_on_net_total_and_skips_actual_and_included(self):
		percent = header_tax_percent_from_charges(
			[
				{"charge_type": "On Net Total", "rate": 18, "add_deduct_tax": "Add"},
				{"charge_type": "Actual", "rate": 50, "add_deduct_tax": "Add"},
				{
					"charge_type": "On Net Total",
					"rate": 12,
					"add_deduct_tax": "Add",
					"included_in_print_rate": 1,
				},
				{"charge_type": "On Net Total", "rate": 5, "add_deduct_tax": "Deduct"},
			]
		)
		self.assertEqual(percent, 13.0)

	def test_applied_tax_prefers_the_item_over_the_header(self):
		self.assertEqual(applied_tax_percent('{"CGST": 9, "SGST": 9}', 5), 18.0)
		self.assertEqual(applied_tax_percent("", 5), 5.0)

	def test_line_invoice_amount_adds_tax_to_qty_times_rate(self):
		# 2 x 100, plus 18% tax -> 236
		self.assertEqual(line_invoice_amount(2, 100, 18), 236.0)

	def test_invoice_amount_for_lines_sums_each_line(self):
		# 2 x 100 x 1.18 = 236; 1 x 80 x 1.05 = 84
		self.assertEqual(invoice_amount_for_lines([(2, 100, 18), (1, 80, 5)]), 320.0)

	def test_zero_tax_is_qty_times_rate(self):
		self.assertEqual(line_invoice_amount(2, 100, 0), 200.0)
