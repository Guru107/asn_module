from types import SimpleNamespace
from unittest.mock import patch

import frappe

from asn_module.barcode_process_flow import runtime
from asn_module.tests.compat import UnitTestCase


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
				return_value={
					"doctype": "Purchase Invoice",
					"name": "PINV-0001",
					"url": "/app/purchase-invoice/PINV-0001",
				},
			),
		):
			result, winners = runtime.dispatch_from_scan(scan_action_key="next", source_doc=source_doc)

		self.assertEqual(result["doctype"], "Purchase Invoice")
		self.assertEqual(len(winners), 1)
		self.assertEqual(winners[0].step_name, "STEP-HIGH")

	def test_dispatch_raises_when_no_candidates(self):
		with patch(
			"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source", return_value=[]
		):
			with self.assertRaises(runtime.StepNotFoundError):
				runtime.dispatch_from_scan(
					scan_action_key="missing",
					source_doc=SimpleNamespace(doctype="ASN", name="ASN-1"),
				)

	def test_dispatch_raises_when_no_eligible_candidates(self):
		steps = [SimpleNamespace(priority=10)]
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=steps,
			),
			patch("asn_module.barcode_process_flow.runtime._is_condition_satisfied", return_value=False),
		):
			with self.assertRaises(runtime.StepNotFoundError):
				runtime.dispatch_from_scan(scan_action_key="x", source_doc=SimpleNamespace(doctype="ASN"))

	def test_dispatch_returns_results_for_parallel_winners(self):
		step_a = SimpleNamespace(flow_name="A", label="L1", step_name="S1", priority=10)
		step_b = SimpleNamespace(flow_name="B", label="L2", step_name="S2", priority=10)
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[step_a, step_b],
			),
			patch("asn_module.barcode_process_flow.runtime._is_condition_satisfied", return_value=True),
			patch(
				"asn_module.barcode_process_flow.runtime.execute_step",
				side_effect=[
					{"doctype": "Purchase Invoice", "name": "PINV-1", "url": "/app/purchase-invoice/PINV-1"},
					{"doctype": "Stock Entry", "name": "STE-1", "url": "/app/stock-entry/STE-1"},
				],
			),
		):
			result, _ = runtime.dispatch_from_scan(
				scan_action_key="x", source_doc=SimpleNamespace(doctype="ASN")
			)
		self.assertIn("results", result)
		self.assertEqual(len(result["results"]), 2)
		self.assertEqual(result["doctype"], "Purchase Invoice")

	def test_resolve_eligible_steps_returns_empty_when_none_match(self):
		step = SimpleNamespace(priority=1)
		with patch("asn_module.barcode_process_flow.runtime._is_condition_satisfied", return_value=False):
			self.assertEqual(runtime.resolve_eligible_steps([step], source_doc=SimpleNamespace()), [])

	def test_generate_codes_for_source_doc_uses_eligible_winners(self):
		source_doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-0001")
		winners = [SimpleNamespace(step_name="STEP-1")]
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[SimpleNamespace(step_name="STEP-1")],
			),
			patch("asn_module.barcode_process_flow.runtime.resolve_eligible_steps", return_value=winners),
			patch(
				"asn_module.barcode_process_flow.runtime._generate_codes_for_steps",
				return_value=[{"action_key": "purchase_receipt_to_purchase_invoice"}],
			) as generate_mock,
		):
			result = runtime.generate_codes_for_source_doc(source_doc=source_doc)

		self.assertEqual(result, [{"action_key": "purchase_receipt_to_purchase_invoice"}])
		generate_mock.assert_called_once_with(source_doc=source_doc, steps=winners)

	def test_generate_codes_for_source_doc_conditioned_only_filters_unconditional_steps(self):
		source_doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-0001")
		steps = [SimpleNamespace(condition=""), SimpleNamespace(condition="PR Submitted")]
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=steps,
			),
			patch(
				"asn_module.barcode_process_flow.runtime.resolve_eligible_steps",
				side_effect=lambda rows, _doc: rows,
			),
			patch(
				"asn_module.barcode_process_flow.runtime._generate_codes_for_steps",
				return_value=[{"action_key": "purchase_receipt_to_purchase_invoice"}],
			) as generate_mock,
		):
			runtime.generate_codes_for_source_doc(source_doc=source_doc, conditioned_only=True)

		filtered_steps = generate_mock.call_args.kwargs["steps"]
		self.assertEqual(len(filtered_steps), 1)
		self.assertEqual(filtered_steps[0].condition, "PR Submitted")

	def test_execute_step_server_script_and_mapping_paths(self):
		step_server = SimpleNamespace(
			execution_mode="Server Script",
			server_script="SS-1",
			label="L",
			flow_name="F",
			step_name="S",
			scan_action_key="K",
			generate_next_barcode=0,
		)
		with patch(
			"asn_module.barcode_process_flow.runtime._execute_server_script",
			return_value={"doctype": "Scan Log", "name": "LOG-1", "url": "/app/scan-log/LOG-1"},
		):
			result_server = runtime.execute_step(step=step_server, source_doc=SimpleNamespace())
		self.assertEqual(result_server["doctype"], "Scan Log")
		self.assertEqual(result_server["generated_scan_codes"], [])

		step_mapping = SimpleNamespace(
			execution_mode="Mapping",
			server_script="",
			label="L",
			flow_name="F",
			step_name="S",
			scan_action_key="K",
			generate_next_barcode=0,
		)
		with patch(
			"asn_module.barcode_process_flow.runtime._execute_mapping",
			return_value={"doctype": "Purchase Receipt", "name": "PR-1", "url": "/app/purchase-receipt/PR-1"},
		):
			result_mapping = runtime.execute_step(step=step_mapping, source_doc=SimpleNamespace())
			self.assertEqual(result_mapping["doctype"], "Purchase Receipt")

	def test_execute_step_generates_followup_codes_when_enabled(self):
		step = SimpleNamespace(
			execution_mode="Mapping",
			server_script="",
			label="L",
			flow_name="F",
			step_name="S",
			scan_action_key="K",
			generate_next_barcode=1,
		)
		with (
			patch(
				"asn_module.barcode_process_flow.runtime._execute_mapping",
				return_value={
					"doctype": "Purchase Receipt",
					"name": "PR-1",
					"url": "/app/purchase-receipt/PR-1",
				},
			),
			patch(
				"asn_module.barcode_process_flow.runtime._generate_followup_codes",
				return_value=[{"scan_code": "ABCD"}],
			),
		):
			result = runtime.execute_step(step=step, source_doc=SimpleNamespace())
		self.assertEqual(result["generated_scan_codes"], [{"scan_code": "ABCD"}])

	def test_execute_mapping_uses_handler_and_fallback_mapping_set(self):
		step = SimpleNamespace(
			from_doctype="ASN",
			to_doctype="Purchase Receipt",
			mapping_set="MAP-1",
			label="L",
			scan_action_key="asn_to_purchase_receipt",
		)
		source_doc = SimpleNamespace(name="ASN-1")
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.capabilities.get_standard_handler",
				return_value="x.y.z",
			) as get_handler,
			patch(
				"asn_module.barcode_process_flow.runtime.frappe.get_attr",
				return_value=lambda *_: {
					"doctype": "Purchase Receipt",
					"name": "PR-1",
					"url": "/app/purchase-receipt/PR-1",
				},
			),
		):
			result = runtime._execute_mapping(step=step, source_doc=source_doc)
		get_handler.assert_called_once_with(
			from_doctype="ASN",
			to_doctype="Purchase Receipt",
			source_doc=source_doc,
			action_key="asn_to_purchase_receipt",
		)
		self.assertEqual(result["name"], "PR-1")

		step_no_map = SimpleNamespace(
			from_doctype="ASN",
			to_doctype="Purchase Receipt",
			mapping_set="",
			label="L",
			scan_action_key="asn_to_purchase_receipt",
		)
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.capabilities.get_standard_handler", return_value=None
			),
			patch("asn_module.barcode_process_flow.runtime.repository.get_mapping_set", return_value=None),
		):
			with self.assertRaises(frappe.ValidationError):
				runtime._execute_mapping(step=step_no_map, source_doc=SimpleNamespace(name="ASN-1"))

		doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-2", insert=lambda **_: None)
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.capabilities.get_standard_handler", return_value=None
			),
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_mapping_set",
				return_value=SimpleNamespace(rows=[1]),
			),
			patch("asn_module.barcode_process_flow.runtime.mapping.build_target_doc", return_value=doc),
		):
			result_doc = runtime._execute_mapping(step=step, source_doc=SimpleNamespace(name="ASN-1"))
		self.assertEqual(result_doc["doctype"], "Purchase Receipt")

	def test_execute_server_script_validation_paths(self):
		step_missing = SimpleNamespace(server_script="", label="L")
		with self.assertRaises(frappe.ValidationError):
			runtime._execute_server_script(step=step_missing, source_doc=SimpleNamespace())

		step = SimpleNamespace(server_script="SS-1", label="L")
		with patch(
			"asn_module.barcode_process_flow.runtime.frappe.get_doc",
			return_value=SimpleNamespace(execute_method=lambda: []),
		):
			with self.assertRaises(frappe.ValidationError):
				runtime._execute_server_script(step=step, source_doc=SimpleNamespace())

		with patch(
			"asn_module.barcode_process_flow.runtime.frappe.get_doc",
			return_value=SimpleNamespace(execute_method=lambda: ["bad"]),
		):
			with self.assertRaises(frappe.ValidationError):
				runtime._execute_server_script(step=step, source_doc=SimpleNamespace())

		with patch(
			"asn_module.barcode_process_flow.runtime.frappe.get_doc",
			return_value=SimpleNamespace(
				execute_method=lambda: {
					"doctype": "Purchase Invoice",
					"name": "PINV-1",
					"url": "/app/purchase-invoice/PINV-1",
				}
			),
		):
			result = runtime._execute_server_script(step=step, source_doc=SimpleNamespace())
		self.assertEqual(result["doctype"], "Purchase Invoice")

	def test_generate_followup_codes_attaches_qr_and_barcode_files(self):
		target_doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-0001")
		step = SimpleNamespace(
			flow_name="FLOW",
			flow_label="Inbound",
			step_name="STEP-PI",
			label="PR to PI",
			from_doctype="Purchase Receipt",
			to_doctype="Purchase Invoice",
			execution_mode="Mapping",
			mapping_set="MAP-1",
			server_script=None,
			condition=None,
			priority=20,
			generate_next_barcode=1,
			generation_mode="immediate",
			scan_action_key="purchase_receipt_to_purchase_invoice",
		)

		def _fake_file(filename, *_args, **_kwargs):
			return SimpleNamespace(file_url=f"/files/{filename}")

		with (
			patch("asn_module.barcode_process_flow.runtime.frappe.get_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[step],
			),
			patch("asn_module.barcode_process_flow.runtime.resolve_eligible_steps", return_value=[step]),
			patch(
				"asn_module.qr_engine.generate.generate_qr",
				return_value={
					"scan_code": "XJWTJAE2MGMNV4SW",
					"human_readable": "XJWTJAE2MGMNV4SW",
					"image_base64": "ZmFrZS1xcg==",
				},
			) as generate_qr_mock,
			patch(
				"asn_module.qr_engine.generate.generate_barcode",
				return_value={
					"scan_code": "XJWTJAE2MGMNV4SW",
					"human_readable": "XJWTJAE2MGMNV4SW",
					"image_base64": "ZmFrZS1iYXI=",
				},
			) as generate_barcode_mock,
			patch("frappe.utils.file_manager.save_file", side_effect=_fake_file) as save_file_mock,
		):
			generated = runtime._generate_followup_codes({"doctype": "Purchase Receipt", "name": "PR-0001"})

		generate_qr_mock.assert_called_once_with(
			"purchase_receipt_to_purchase_invoice",
			"Purchase Receipt",
			"PR-0001",
		)
		generate_barcode_mock.assert_called_once_with(
			"purchase_receipt_to_purchase_invoice",
			"Purchase Receipt",
			"PR-0001",
		)
		self.assertEqual(save_file_mock.call_count, 2)
		self.assertEqual(generated[0]["qr_file_url"], "/files/PR-0001-STEP-PI-qr.png")
		self.assertEqual(generated[0]["barcode_file_url"], "/files/PR-0001-STEP-PI-barcode.png")

	def test_generate_followup_code_guards_and_modes(self):
		self.assertEqual(runtime._generate_followup_codes({"doctype": "", "name": ""}), [])
		target_doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-1")
		step_runtime = SimpleNamespace(
			generate_next_barcode=1,
			generation_mode="runtime",
			scan_action_key="x",
			step_name="S1",
		)
		with (
			patch("asn_module.barcode_process_flow.runtime.frappe.get_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[step_runtime],
			),
			patch(
				"asn_module.barcode_process_flow.runtime.resolve_eligible_steps", return_value=[step_runtime]
			),
		):
			self.assertEqual(
				runtime._generate_followup_codes({"doctype": "Purchase Receipt", "name": "PR-1"}),
				[],
			)

		step_disabled = SimpleNamespace(
			generate_next_barcode=0,
			generation_mode="immediate",
			scan_action_key="x",
			step_name="S1",
		)
		with (
			patch("asn_module.barcode_process_flow.runtime.frappe.get_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_active_steps_for_source",
				return_value=[step_disabled],
			),
			patch(
				"asn_module.barcode_process_flow.runtime.resolve_eligible_steps", return_value=[step_disabled]
			),
		):
			self.assertEqual(
				runtime._generate_followup_codes({"doctype": "Purchase Receipt", "name": "PR-1"}),
				[],
			)

	def test_misc_runtime_helpers(self):
		self.assertEqual(runtime._pick_winners([]), [])
		steps = [
			SimpleNamespace(priority=10, flow_name="B", label="L2", step_name="S2"),
			SimpleNamespace(priority=10, flow_name="A", label="L1", step_name="S1"),
		]
		winners = runtime._pick_winners(steps)
		self.assertEqual(winners[0].flow_name, "A")

		with patch("asn_module.barcode_process_flow.runtime.repository.get_rule", return_value=None):
			self.assertTrue(runtime._is_condition_satisfied(SimpleNamespace(condition=""), SimpleNamespace()))
		with (
			patch(
				"asn_module.barcode_process_flow.runtime.repository.get_rule",
				return_value=SimpleNamespace(),
			),
			patch("asn_module.barcode_process_flow.runtime.rules.evaluate_rule", return_value=False),
		):
			self.assertFalse(
				runtime._is_condition_satisfied(SimpleNamespace(condition="R1"), SimpleNamespace())
			)

		self.assertEqual(
			runtime._doc_contract(SimpleNamespace(doctype="Purchase Receipt", name="PR-1"))["url"],
			"/app/purchase_receipt/PR-1",
		)
		with self.assertRaises(frappe.ValidationError):
			runtime._validate_contract([])
		with self.assertRaises(frappe.ValidationError):
			runtime._validate_contract({"doctype": "Purchase Receipt"})
		self.assertEqual(
			runtime._validate_contract({"doctype": "D", "name": "N", "url": "/x"})["name"],
			"N",
		)

		class NoDataclass:
			def __init__(self):
				self.flow_name = "F"
				self.flow_label = "FL"
				self.step_name = "S"
				self.label = "L"
				self.from_doctype = "ASN"
				self.to_doctype = "Purchase Receipt"
				self.priority = 1
				self.scan_action_key = "K"

		serialized = runtime._serialize_step(NoDataclass())
		self.assertEqual(serialized["flow_name"], "F")

		self.assertEqual(runtime._safe_file_segment("A/B\\C"), "A-B-C")
