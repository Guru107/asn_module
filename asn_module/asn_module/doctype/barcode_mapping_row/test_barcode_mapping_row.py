from types import SimpleNamespace
from unittest import TestCase

import frappe

from asn_module.asn_module.doctype.barcode_mapping_row.barcode_mapping_row import BarcodeMappingRow


class TestBarcodeMappingRow(TestCase):
	def test_validate_requires_constant_value_for_constant_mapping(self):
		doc = SimpleNamespace(
			mapping_type="constant",
			source_field="",
			target_field="Purchase Receipt.supplier",
			transform="",
			constant_value="   ",
		)
		with self.assertRaises(frappe.ValidationError):
			BarcodeMappingRow.validate(doc)

	def test_validate_accepts_source_mapping_without_constant_value(self):
		doc = SimpleNamespace(
			mapping_type="source",
			source_field="ASN.supplier",
			target_field="Purchase Receipt.supplier",
			transform="",
			constant_value=None,
		)
		BarcodeMappingRow.validate(doc)
