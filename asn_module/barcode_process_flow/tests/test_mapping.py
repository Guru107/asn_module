from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow.mapping import build_target_doc
from asn_module.tests.compat import UnitTestCase


class TestMapping(UnitTestCase):
	def test_mapping_set_copies_item_rows_from_asn_to_pr(self):
		source = SimpleNamespace(
			supplier="SUP-0001",
			items=[
				SimpleNamespace(item_code="ITEM-001", qty=2),
				SimpleNamespace(item_code="ITEM-002", qty=4),
			],
		)
		rows = [
			SimpleNamespace(mapping_type="source", source_selector="supplier", target_selector="supplier", transform=""),
			SimpleNamespace(
				mapping_type="source",
				source_selector="items[].item_code",
				target_selector="items[].item_code",
				transform="",
			),
			SimpleNamespace(mapping_type="source", source_selector="items[].qty", target_selector="items[].qty", transform=""),
		]

		with patch("asn_module.barcode_process_flow.mapping.frappe.get_doc", side_effect=lambda payload: payload):
			target = build_target_doc(source_doc=source, mapping_rows=rows, target_doctype="Purchase Receipt")

		self.assertEqual(target["doctype"], "Purchase Receipt")
		self.assertEqual(target["supplier"], "SUP-0001")
		self.assertEqual(len(target["items"]), 2)
		self.assertEqual(target["items"][0]["item_code"], "ITEM-001")
		self.assertEqual(target["items"][1]["qty"], 4)
