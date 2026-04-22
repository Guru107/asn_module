from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from asn_module.barcode_process_flow.runtime import dispatch_from_scan


class TestBarcodeProcessFlowIntegration(FrappeTestCase):
	def test_dispatch_from_scan_executes_step_and_returns_contract(self):
		source_doc = SimpleNamespace(doctype="ASN", name="ASN-0001")
		step = SimpleNamespace(
			flow_name="FLOW-INBOUND",
			flow_label="Inbound",
			step_name="STEP-0001",
			label="ASN -> Purchase Receipt",
			from_doctype="ASN",
			to_doctype="Purchase Receipt",
			execution_mode="Mapping",
			mapping_set="MAP-1",
			server_script=None,
			condition=None,
			priority=100,
			generate_next_barcode=0,
			generation_mode="hybrid",
			scan_action_key="STEP-INBOUND",
		)

		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[step],
			),
			patch("asn_module.barcode_process_flow.runtime._is_condition_satisfied", return_value=True),
			patch(
				"asn_module.barcode_process_flow.runtime.execute_step",
				return_value={
					"doctype": "Purchase Receipt",
					"name": "MAT-PRE-0001",
					"url": "/app/purchase-receipt/MAT-PRE-0001",
					"message": "created",
				},
			),
		):
			result, winners = dispatch_from_scan(scan_action_key="STEP-INBOUND", source_doc=source_doc)

		self.assertEqual(result["doctype"], "Purchase Receipt")
		self.assertEqual(len(winners), 1)
		self.assertEqual(winners[0].flow_name, "FLOW-INBOUND")
