from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from asn_module.asn_module.doctype.barcode_mapping_set import barcode_mapping_set
from asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set import BarcodeMappingSet


class TestBarcodeMappingSetHelpers(TestCase):
	def test_search_mappable_docfields_returns_empty_without_parent_doctype(self):
		rows = barcode_mapping_set.search_mappable_docfields("DocField", "", "fieldname", 0, 20, filters={})
		self.assertEqual(rows, [])

	def test_search_mappable_docfields_queries_parent_and_items_doctype(self):
		with (
			patch(
				"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._get_items_child_doctype",
				return_value="ASN Item",
			),
			patch(
				"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set.frappe.db.sql",
				return_value=[["ASN.supplier", "Header :: supplier — Supplier", "DOCFIELD-1"]],
			) as sql,
			):
				rows = barcode_mapping_set.search_mappable_docfields(
				"DocField",
				"supp",
				"fieldname",
				0,
				20,
				filters={"parent_doctype": "ASN"},
				)

		self.assertEqual(rows, [["ASN.supplier", "Header :: supplier — Supplier"]])
		params = sql.call_args.args[1]
		self.assertEqual(params["parents"], ("ASN", "ASN Item"))
		self.assertEqual(params["parent_doctype"], "ASN")
		self.assertEqual(params["search_text"], "supp")
		self.assertEqual(params["search_like"], "%supp%")

	def test_get_mappable_field_options_returns_values_only(self):
		with patch(
			"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._mappable_docfields_rows",
			return_value=[
				["ASN.supplier", "Header :: supplier — Supplier"],
				["ASN Item.item_code", "Items :: item_code — Item Code"],
			],
		):
			self.assertEqual(
				barcode_mapping_set.get_mappable_field_options("ASN"),
				["ASN.supplier", "ASN Item.item_code"],
			)

	def test_selector_from_docfield_resolves_source_and_target_paths(self):
		with patch(
			"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._get_items_child_doctype",
			return_value="ASN Item",
		):
			self.assertEqual(
				barcode_mapping_set._selector_from_docfield("ASN.supplier", "ASN", "source"),
				"header.supplier",
			)
			self.assertEqual(
				barcode_mapping_set._selector_from_docfield("ASN.supplier", "ASN", "target"),
				"supplier",
			)
			self.assertEqual(
				barcode_mapping_set._selector_from_docfield("ASN Item.item_code", "ASN", "source"),
				"items[].item_code",
			)

	def test_selector_from_docfield_accepts_legacy_docfield_name(self):
		with (
			patch(
				"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set.frappe.db.get_value",
				return_value={"parent": "ASN", "fieldname": "supplier"},
			),
			patch(
				"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._get_items_child_doctype",
				return_value="ASN Item",
			),
		):
			self.assertEqual(
				barcode_mapping_set._selector_from_docfield("DOCFIELD-ROW-ID", "ASN", "source"),
				"header.supplier",
			)


class TestBarcodeMappingSetValidation(TestCase):
	def test_validate_requires_valid_source_and_target_fields(self):
		row = SimpleNamespace(
			mapping_type="source",
			source_field="ASN.supplier",
			target_field="Purchase Receipt Item.item_code",
		)
		doc = SimpleNamespace(
			mapping_set_name="  MAP-1  ",
			source_doctype="  ASN  ",
			target_doctype="  Purchase Receipt  ",
			rows=[row],
		)
		with patch(
			"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._selector_from_docfield",
			side_effect=["header.supplier", "items[].item_code"],
		) as selector_resolver:
			BarcodeMappingSet.validate(doc)

		self.assertEqual(doc.mapping_set_name, "MAP-1")
		self.assertEqual(doc.source_doctype, "ASN")
		self.assertEqual(doc.target_doctype, "Purchase Receipt")
		self.assertEqual(selector_resolver.call_count, 2)

	def test_validate_raises_for_invalid_target_field(self):
		row = SimpleNamespace(
			mapping_type="constant",
			source_field="",
			target_field="Stock Entry.item_code",
		)
		doc = SimpleNamespace(
			mapping_set_name="MAP-1",
			source_doctype="ASN",
			target_doctype="Purchase Receipt",
			rows=[row],
		)
		with (
			patch(
				"asn_module.asn_module.doctype.barcode_mapping_set.barcode_mapping_set._selector_from_docfield",
				return_value="",
			),
			self.assertRaises(frappe.ValidationError),
		):
			BarcodeMappingSet.validate(doc)
