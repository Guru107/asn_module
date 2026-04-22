from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow.repository import get_active_steps_for_source
from asn_module.tests.compat import UnitTestCase


class TestRepository(UnitTestCase):
	def test_flow_step_requires_from_to_doctype(self):
		source = SimpleNamespace(doctype="ASN", supplier="", supplier_type="", company="", warehouse="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="",
			warehouse="",
			supplier_type="",
			steps=[SimpleNamespace(name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label="")],
		)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=["FLOW-1"]),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
		):
			rows = get_active_steps_for_source(source)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].from_doctype, "ASN")
		self.assertEqual(rows[0].to_doctype, "Purchase Receipt")
