from unittest import TestCase
from unittest.mock import patch

from asn_module.custom_fields import purchase_invoice, purchase_receipt


class TestCustomFieldSetup(TestCase):
	def test_purchase_invoice_setup_creates_expected_field(self):
		with patch("asn_module.custom_fields.purchase_invoice.create_custom_fields") as create_custom_fields:
			purchase_invoice.setup()

		fields_map = create_custom_fields.call_args.args[0]
		self.assertIn("Purchase Invoice", fields_map)
		self.assertEqual(fields_map["Purchase Invoice"][0]["fieldname"], "asn")

	def test_purchase_receipt_setup_creates_expected_fields(self):
		with patch("asn_module.custom_fields.purchase_receipt.create_custom_fields") as create_custom_fields:
			purchase_receipt.setup()

		fields_map = create_custom_fields.call_args.args[0]
		self.assertIn("Purchase Receipt", fields_map)
		fieldnames = [row["fieldname"] for row in fields_map["Purchase Receipt"]]
		self.assertEqual(fieldnames, ["asn", "asn_items"])
