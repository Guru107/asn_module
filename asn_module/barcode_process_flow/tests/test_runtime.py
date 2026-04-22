from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import UnitTestCase

from asn_module.barcode_process_flow.runtime import dispatch_from_scan


class TestRuntime(UnitTestCase):
	def test_runtime_picks_highest_priority_eligible_step(self):
		source_doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-0001")
		steps = [
			SimpleNamespace(
				flow_name="FLOW",
				flow_label="Inbound",
				step_name="STEP-LOW",
				label="PR to PI",
				from_doctype="Purchase Receipt",
				to_doctype="Purchase Invoice",
				execution_mode="Mapping",
				mapping_set="MAP-1",
				server_script=None,
				condition=None,
				priority=10,
				generate_next_barcode=0,
				generation_mode="hybrid",
				scan_action_key="next",
			),
			SimpleNamespace(
				flow_name="FLOW",
				flow_label="Inbound",
				step_name="STEP-HIGH",
				label="PR to PI High",
				from_doctype="Purchase Receipt",
				to_doctype="Purchase Invoice",
				execution_mode="Mapping",
				mapping_set="MAP-1",
				server_script=None,
				condition=None,
				priority=20,
				generate_next_barcode=0,
				generation_mode="hybrid",
				scan_action_key="next",
			),
		]

		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=steps,
			),
			patch("asn_module.barcode_process_flow.runtime._is_condition_satisfied", return_value=True),
			patch(
				"asn_module.barcode_process_flow.runtime.execute_step",
				return_value={"doctype": "Purchase Invoice", "name": "PINV-0001", "url": "/app/purchase-invoice/PINV-0001"},
			),
		):
			result, winners = dispatch_from_scan(scan_action_key="next", source_doc=source_doc)

		self.assertEqual(result["doctype"], "Purchase Invoice")
		self.assertEqual(len(winners), 1)
		self.assertEqual(winners[0].step_name, "STEP-HIGH")
