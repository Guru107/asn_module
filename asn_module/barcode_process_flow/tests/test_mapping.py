from types import SimpleNamespace
from unittest.mock import patch

import frappe

from asn_module.barcode_process_flow import mapping
from asn_module.tests.compat import UnitTestCase


class TestMapping(UnitTestCase):
	def test_mapping_set_copies_item_rows_from_asn_to_pr(self):
		source = SimpleNamespace(
			doctype="ASN",
			supplier="SUP-0001",
			items=[
				SimpleNamespace(item_code="ITEM-001", qty=2),
				SimpleNamespace(item_code="ITEM-002", qty=4),
			],
		)
		rows = [
			SimpleNamespace(
				mapping_type="source",
				source_field="ASN.supplier",
				target_field="Purchase Receipt.supplier",
				transform="",
			),
			SimpleNamespace(
				mapping_type="source",
				source_field="ASN Item.item_code",
				target_field="Purchase Receipt Item.item_code",
				transform="",
			),
			SimpleNamespace(
				mapping_type="source",
				source_field="ASN Item.qty",
				target_field="Purchase Receipt Item.qty",
				transform="",
			),
		]

		with (
			patch(
				"asn_module.barcode_process_flow.mapping._get_items_child_doctype",
				side_effect=lambda doctype: {
					"ASN": "ASN Item",
					"Purchase Receipt": "Purchase Receipt Item",
				}.get(doctype, ""),
			),
			patch(
				"asn_module.barcode_process_flow.mapping.frappe.get_doc", side_effect=lambda payload: payload
			),
		):
			target = mapping.build_target_doc(
				source_doc=source, mapping_rows=rows, target_doctype="Purchase Receipt"
			)

		self.assertEqual(target["doctype"], "Purchase Receipt")
		self.assertEqual(target["supplier"], "SUP-0001")
		self.assertEqual(len(target["items"]), 2)
		self.assertEqual(target["items"][0]["item_code"], "ITEM-001")
		self.assertEqual(target["items"][1]["qty"], 4)

	def test_build_target_doc_raises_when_target_field_is_invalid(self):
		source = SimpleNamespace(doctype="ASN", supplier="SUP-0001", items=[])
		rows = [
			SimpleNamespace(
				mapping_type="source",
				source_field="ASN.supplier",
				target_field="",
				transform="",
			)
		]
		with self.assertRaises(frappe.ValidationError):
			mapping.build_target_doc(source_doc=source, mapping_rows=rows, target_doctype="Purchase Receipt")

	def test_build_target_items_returns_empty_when_source_has_no_items(self):
		source = SimpleNamespace(items=[])
		rows = [
			{
				"row": SimpleNamespace(mapping_type="source", transform=""),
				"source_selector": "items[].item_code",
				"target_selector": "items[].item_code",
			}
		]
		self.assertEqual(mapping._build_target_items(source_doc=source, item_rows=rows), [])

	def test_row_value_constant_and_transforms(self):
		row = SimpleNamespace(mapping_type="constant", constant_value="abc", transform="upper")
		self.assertEqual(
			mapping._resolve_row_value(row=row, source_doc=SimpleNamespace(), source_item=None), "ABC"
		)
		self.assertEqual(mapping._apply_transform("AbC", "lower"), "abc")
		self.assertEqual(mapping._apply_transform("10", "int"), 10)
		self.assertEqual(mapping._apply_transform("10.5", "float"), 10.5)
		self.assertEqual(mapping._apply_transform(None, "str"), "")
		self.assertEqual(mapping._apply_transform("x", "unknown"), "x")

	def test_source_selector_resolution_paths(self):
		source = SimpleNamespace(company="TCPL", items=[SimpleNamespace(item_code="ITM-1")])
		item = source.items[0]
		self.assertEqual(
			mapping._resolve_source_selector(source_doc=source, source_item=item, selector="header.company"),
			"TCPL",
		)
		self.assertEqual(
			mapping._resolve_source_selector(
				source_doc=source, source_item=item, selector="items[].item_code"
			),
			"ITM-1",
		)
		self.assertIsNone(
			mapping._resolve_source_selector(
				source_doc=source, source_item=None, selector="items[].item_code"
			)
		)
		self.assertEqual(
			mapping._resolve_source_selector(source_doc=source, source_item=item, selector="company"), "TCPL"
		)
		self.assertIsNone(mapping._resolve_source_selector(source_doc=source, source_item=item, selector=""))

	def test_normalize_target_selector(self):
		self.assertEqual(mapping._normalize_target_selector("target.company"), "company")
		self.assertEqual(mapping._normalize_target_selector("items[].qty"), "items[].qty")

	def test_selector_from_docfield_reference_resolves_header_and_items(self):
		selector_cache = {}
		with (
			patch(
				"asn_module.barcode_process_flow.mapping._get_items_child_doctype",
				side_effect=lambda doctype: {
					"ASN": "ASN Item",
					"Purchase Receipt": "Purchase Receipt Item",
				}.get(doctype, ""),
			),
		):
			self.assertEqual(
				mapping._selector_from_docfield_reference(
					docfield_reference="ASN.supplier",
					parent_doctype="ASN",
					side="source",
					selector_cache=selector_cache,
				),
				"header.supplier",
			)
			self.assertEqual(
				mapping._selector_from_docfield_reference(
					docfield_reference="ASN Item.item_code",
					parent_doctype="ASN",
					side="source",
					selector_cache=selector_cache,
				),
				"items[].item_code",
			)
			self.assertEqual(
				mapping._selector_from_docfield_reference(
					docfield_reference="Purchase Receipt.supplier",
					parent_doctype="Purchase Receipt",
					side="target",
					selector_cache=selector_cache,
				),
				"supplier",
			)

	def test_selector_from_docfield_reference_returns_empty_for_mismatch(self):
		selector_cache = {}
		with patch(
			"asn_module.barcode_process_flow.mapping._get_items_child_doctype",
			return_value="Purchase Receipt Item",
		):
			self.assertEqual(
				mapping._selector_from_docfield_reference(
					docfield_reference="Stock Entry.warehouse",
					parent_doctype="Purchase Receipt",
					side="target",
					selector_cache=selector_cache,
				),
				"",
			)

	def test_selector_from_docfield_reference_accepts_legacy_docfield_name(self):
		selector_cache = {}
		with (
			patch(
				"asn_module.barcode_process_flow.mapping.frappe.db.get_value",
				return_value={"parent": "ASN", "fieldname": "supplier"},
			),
			patch(
				"asn_module.barcode_process_flow.mapping._get_items_child_doctype", return_value="ASN Item"
			),
		):
			self.assertEqual(
				mapping._selector_from_docfield_reference(
					docfield_reference="DOCFIELD-ROW-ID",
					parent_doctype="ASN",
					side="source",
					selector_cache=selector_cache,
				),
				"header.supplier",
			)

	def test_resolve_dotted_for_dict_object_and_getter(self):
		self.assertEqual(mapping._resolve_dotted({"a": {"b": 1}}, "a.b"), 1)
		self.assertIsNone(mapping._resolve_dotted({"a": {}}, "a.b"))
		self.assertEqual(mapping._resolve_dotted(SimpleNamespace(a=SimpleNamespace(b=2)), "a.b"), 2)

		class GetterOnly:
			def __init__(self):
				self.values = {"x": 7}

			def get(self, key):
				return self.values.get(key)

		self.assertEqual(mapping._resolve_dotted(GetterOnly(), "x"), 7)
		self.assertIsNone(mapping._resolve_dotted(None, "x"))

	def test_set_dotted_paths(self):
		payload = {}
		mapping._set_dotted(payload, "company", "TCPL")
		mapping._set_dotted(payload, "meta.owner", "Administrator")
		mapping._set_dotted(payload, "", "ignored")
		self.assertEqual(payload["company"], "TCPL")
		self.assertEqual(payload["meta"]["owner"], "Administrator")

	def test_get_value_supports_dict_and_object(self):
		self.assertEqual(mapping._get_value({"a": 1}, "a"), 1)
		self.assertEqual(mapping._get_value(SimpleNamespace(a=2), "a"), 2)
