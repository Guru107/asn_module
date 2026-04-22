import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

frappe_stub = sys.modules.get("frappe")
if frappe_stub is None:
	frappe_stub = ModuleType("frappe")
	sys.modules["frappe"] = frappe_stub
if not hasattr(frappe_stub, "ValidationError"):
	frappe_stub.ValidationError = type("ValidationError", (Exception,), {})
if not hasattr(frappe_stub, "DoesNotExistError"):
	frappe_stub.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
if not hasattr(frappe_stub, "get_attr"):
	frappe_stub.get_attr = lambda _path: None
if not hasattr(frappe_stub, "get_doc"):
	frappe_stub.get_doc = lambda payload: payload
if not hasattr(frappe_stub, "get_all"):
	frappe_stub.get_all = lambda *args, **kwargs: []

frappe_utils_stub = sys.modules.get("frappe.utils")
if frappe_utils_stub is None:
	frappe_utils_stub = ModuleType("frappe.utils")
	sys.modules["frappe.utils"] = frappe_utils_stub
if not hasattr(frappe_utils_stub, "cint"):
	frappe_utils_stub.cint = lambda value: int(value or 0)

import frappe

from asn_module.barcode_flow.cache import (
	get_cached_condition,
	get_cached_transitions_for_source_node_action,
)
from asn_module.barcode_flow.repository import get_condition, get_transitions_for_source_node_action
from asn_module.barcode_flow.runtime import execute_transition_binding


class _FakeTargetDoc:
	def __init__(self, doctype="Purchase Receipt", name="PR-0001"):
		self.doctype = doctype
		self.name = name
		self.insert_calls = []

	def insert(self, ignore_permissions=False):
		self.insert_calls.append(ignore_permissions)
		return self

	def get_url(self):
		return f"/app/{self.doctype.lower().replace(' ', '-')}/{self.name}"


class TestBarcodeFlowRuntime(TestCase):
	def _handler_result(self, name="PR-0009"):
		return {
			"doctype": "Purchase Receipt",
			"name": name,
			"url": f"/app/purchase-receipt/{name}",
		}

	def test_get_transitions_for_source_node_and_action_is_flow_scoped(self):
		transition_docs = {
			"TRANS-HIGH": SimpleNamespace(name="TRANS-HIGH", enabled=1),
			"TRANS-DISABLED": SimpleNamespace(name="TRANS-DISABLED", enabled=0),
			"TRANS-LOW": SimpleNamespace(name="TRANS-LOW", enabled=1),
		}

		with (
			patch(
				"asn_module.barcode_flow.repository.frappe.get_all",
				return_value=["TRANS-HIGH", "TRANS-DISABLED", "TRANS-LOW"],
			) as get_all,
			patch(
				"asn_module.barcode_flow.repository.frappe.get_doc",
				side_effect=lambda doctype, name: transition_docs[name],
			) as get_doc,
		):
			rows = get_transitions_for_source_node_action(
				flow="FLOW-1",
				source_node="NODE-1",
				action="ACT-1",
			)

		self.assertEqual([row.name for row in rows], ["TRANS-HIGH", "TRANS-LOW"])
		self.assertEqual(
			get_all.call_args.kwargs["filters"],
			{"flow": "FLOW-1", "source_node": "NODE-1", "action": "ACT-1"},
		)
		self.assertEqual(get_all.call_args.kwargs["order_by"], "priority asc, creation asc, name asc")
		self.assertEqual(get_doc.call_count, 3)

	def test_get_condition_returns_enabled_condition_and_excludes_disabled_or_missing(self):
		enabled = SimpleNamespace(name="COND-ENABLED", enabled=1)
		disabled = SimpleNamespace(name="COND-DISABLED", enabled=0)

		def _get_doc(_doctype, name):
			if name == "COND-ENABLED":
				return enabled
			if name == "COND-DISABLED":
				return disabled
			raise frappe.DoesNotExistError(name)

		with patch("asn_module.barcode_flow.repository.frappe.get_doc", side_effect=_get_doc):
			self.assertIs(get_condition("COND-ENABLED"), enabled)
			self.assertIsNone(get_condition("COND-DISABLED"))
			self.assertIsNone(get_condition("COND-MISSING"))

	def test_cached_relational_helpers_memoize_repository_calls(self):
		cache_holder = SimpleNamespace()
		transitions = [SimpleNamespace(name="TRANS-1")]
		condition = SimpleNamespace(name="COND-1", enabled=1)

		with (
			patch(
				"asn_module.barcode_flow.cache.repository.get_transitions_for_source_node_action",
				return_value=transitions,
			) as get_transitions,
			patch(
				"asn_module.barcode_flow.cache.repository.get_condition",
				return_value=condition,
			) as get_condition_doc,
		):
			first_transitions = get_cached_transitions_for_source_node_action(
				cache_holder,
				flow="FLOW-1",
				source_node="NODE-1",
				action="ACT-1",
			)
			second_transitions = get_cached_transitions_for_source_node_action(
				cache_holder,
				flow="FLOW-1",
				source_node="NODE-1",
				action="ACT-1",
			)
			first_condition = get_cached_condition("COND-1", cache_holder=cache_holder)
			second_condition = get_cached_condition("COND-1", cache_holder=cache_holder)

		self.assertIs(first_transitions, second_transitions)
		self.assertIs(first_condition, second_condition)
		get_transitions.assert_called_once_with(flow="FLOW-1", source_node="NODE-1", action="ACT-1")
		get_condition_doc.assert_called_once_with("COND-1")

	def test_custom_handler_mode_calls_handler_and_returns_contract(self):
		handler = MagicMock(return_value=self._handler_result())
		action_binding = SimpleNamespace(custom_handler="fake.module.handler")
		transition = SimpleNamespace(binding_mode="custom_handler", action_binding=action_binding)
		source_doc = {"doctype": "ASN", "name": "ASN-0001"}

		with (
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
			patch("asn_module.barcode_flow.runtime.build_target_doc") as build_target_doc,
		):
			result = execute_transition_binding(transition=transition, source_doc=source_doc)

		build_target_doc.assert_not_called()
		handler.assert_called_once()
		self.assertEqual(handler.call_args.kwargs["source_doctype"], "ASN")
		self.assertEqual(handler.call_args.kwargs["source_name"], "ASN-0001")
		payload = handler.call_args.kwargs["payload"]
		self.assertIs(payload["transition"], transition)
		self.assertIs(payload["action_binding"], action_binding)
		self.assertIsNone(payload["target_doc"])
		self.assertEqual(result["doctype"], "Purchase Receipt")
		self.assertEqual(result["name"], "PR-0009")
		self.assertEqual(result["url"], "/app/purchase-receipt/PR-0009")
		self.assertEqual(result["generated_scan_codes"], [])

	def test_mapping_mode_builds_and_inserts_target_doc(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			field_maps=[
				SimpleNamespace(
					mapping_type="constant", target_field_path="supplier", constant_value="SUP-001"
				)
			],
		)
		target_doc = _FakeTargetDoc()

		with patch(
			"asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc
		) as build_target_doc:
			result = execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		build_target_doc.assert_called_once()
		self.assertEqual(target_doc.insert_calls, [True])
		self.assertEqual(result["doctype"], "Purchase Receipt")
		self.assertEqual(result["name"], "PR-0001")
		self.assertEqual(result["url"], "/app/purchase-receipt/PR-0001")

	def test_mapping_mode_resolves_field_map_by_key_from_flow_definition(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			field_map="FLOW-1-MAP-warehouse-map",
		)
		target_doc = _FakeTargetDoc()
		field_map = SimpleNamespace(
			name="FLOW-1-MAP-warehouse-map",
			mapping_type="constant",
			target_field_path="set_warehouse",
			constant_value="WH-001",
		)

		with (
			patch(
				"asn_module.barcode_flow.runtime.frappe.get_doc",
				side_effect=lambda doctype, name: field_map if doctype == "Barcode Flow Field Map" else None,
			),
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc) as build_target_doc,
		):
			execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
			)

		self.assertEqual(build_target_doc.call_args.kwargs["target_doctype"], "Purchase Receipt")
		resolved_mappings = build_target_doc.call_args.kwargs["mappings"]
		self.assertEqual(len(resolved_mappings), 1)
		self.assertEqual(resolved_mappings[0].name, "FLOW-1-MAP-warehouse-map")

	def test_mapping_mode_supports_legacy_field_map_resolution_from_flow_definition(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			field_map_key="warehouse-map",
		)
		flow_definition = SimpleNamespace(
			field_maps=[
				SimpleNamespace(
					map_key="warehouse-map",
					mapping_type="constant",
					target_field_path="set_warehouse",
					constant_value="WH-001",
				)
			]
		)
		target_doc = _FakeTargetDoc()

		with patch(
			"asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc
		) as build_target_doc:
			execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		self.assertEqual(build_target_doc.call_args.kwargs["target_doctype"], "Purchase Receipt")
		resolved_mappings = build_target_doc.call_args.kwargs["mappings"]
		self.assertEqual(len(resolved_mappings), 1)
		self.assertEqual(resolved_mappings[0].map_key, "warehouse-map")

	def test_hybrid_mode_pre_generates_child_code(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			flow="FLOW-1",
			target_node="FLOW-1-NODE-received",
			field_maps=[],
		)
		flow_definition = SimpleNamespace(name="FLOW-1")
		target_doc = _FakeTargetDoc()
		action_definition = SimpleNamespace(name="ACT-confirm_putaway", action_key="confirm_putaway")
		child_transition = SimpleNamespace(
			transition_key="to-putaway",
			source_node="FLOW-1-NODE-received",
			action=action_definition.name,
			generation_mode="hybrid",
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_flow.runtime._get_transitions_for_source_node",
				return_value=[child_transition],
			),
			patch(
				"asn_module.barcode_flow.runtime._get_action_definition",
				return_value=action_definition,
			),
			patch(
				"asn_module.barcode_flow.runtime.build_scan_code_metadata",
				return_value={
					"action_key": "confirm_putaway",
					"scan_code": "PUTAWAY123",
					"human_readable": "PUTAWAY123",
					"generation_mode": "hybrid",
				},
			) as build_metadata,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		build_metadata.assert_called_once_with(
			action_key="confirm_putaway",
			source_doctype="Purchase Receipt",
			source_name="PR-0001",
			generation_mode="hybrid",
		)
		self.assertEqual(len(result["generated_scan_codes"]), 1)
		self.assertEqual(result["generated_scan_codes"][0]["action_key"], "confirm_putaway")

	def test_immediate_mode_pre_generates_child_code(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			flow="FLOW-1",
			target_node="FLOW-1-NODE-received",
			field_maps=[],
		)
		flow_definition = SimpleNamespace(name="FLOW-1")
		target_doc = _FakeTargetDoc()
		action_definition = SimpleNamespace(
			name="ACT-create_purchase_invoice",
			action_key="create_purchase_invoice",
		)
		child_transition = SimpleNamespace(
			transition_key="to-invoice",
			source_node="FLOW-1-NODE-received",
			action=action_definition.name,
			generation_mode="immediate",
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_flow.runtime._get_transitions_for_source_node",
				return_value=[child_transition],
			),
			patch(
				"asn_module.barcode_flow.runtime._get_action_definition",
				return_value=action_definition,
			),
			patch(
				"asn_module.barcode_flow.runtime.build_scan_code_metadata",
				return_value={
					"action_key": "create_purchase_invoice",
					"scan_code": "INV123",
					"human_readable": "INV123",
					"generation_mode": "immediate",
				},
			) as build_metadata,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		build_metadata.assert_called_once_with(
			action_key="create_purchase_invoice",
			source_doctype="Purchase Receipt",
			source_name="PR-0001",
			generation_mode="immediate",
		)
		self.assertEqual(len(result["generated_scan_codes"]), 1)
		self.assertEqual(result["generated_scan_codes"][0]["action_key"], "create_purchase_invoice")

	def test_runtime_mode_does_not_pre_generate_child_codes(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			flow="FLOW-1",
			target_node="FLOW-1-NODE-received",
			field_maps=[],
		)
		flow_definition = SimpleNamespace(name="FLOW-1")
		target_doc = _FakeTargetDoc()
		child_transition = SimpleNamespace(
			transition_key="to-runtime-only",
			source_node="FLOW-1-NODE-received",
			action="ACT-create_purchase_invoice",
			generation_mode="runtime",
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_flow.runtime._get_transitions_for_source_node",
				return_value=[child_transition],
			),
			patch("asn_module.barcode_flow.runtime.build_scan_code_metadata") as build_metadata,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		build_metadata.assert_not_called()
		self.assertEqual(result["generated_scan_codes"], [])

	def test_condition_gated_child_generation_only_includes_true_conditions(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			flow="FLOW-1",
			target_node="FLOW-1-NODE-received",
			field_maps=[],
		)
		flow_definition = SimpleNamespace(name="FLOW-1")
		target_doc = _FakeTargetDoc()
		allow_condition = SimpleNamespace(name="COND-ALLOW")
		block_condition = SimpleNamespace(name="COND-BLOCK")
		invoice_action = SimpleNamespace(
			name="ACT-create_purchase_invoice",
			action_key="create_purchase_invoice",
		)
		putaway_action = SimpleNamespace(name="ACT-confirm_putaway", action_key="confirm_putaway")
		allowed_transition = SimpleNamespace(
			transition_key="to-invoice-allowed",
			source_node="FLOW-1-NODE-received",
			action=invoice_action.name,
			generation_mode="hybrid",
			condition=allow_condition.name,
		)
		blocked_transition = SimpleNamespace(
			transition_key="to-putaway-blocked",
			source_node="FLOW-1-NODE-received",
			action=putaway_action.name,
			generation_mode="immediate",
			condition=block_condition.name,
		)

		def _condition_result(_doc, rules):
			return rules[0].name == "COND-ALLOW"

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_flow.runtime._get_transitions_for_source_node",
				return_value=[allowed_transition, blocked_transition],
			),
			patch(
				"asn_module.barcode_flow.runtime._get_action_definition",
				side_effect=[invoice_action, putaway_action],
			),
			patch(
				"asn_module.barcode_flow.runtime.get_cached_condition",
				side_effect=[allow_condition, block_condition],
			),
			patch(
				"asn_module.barcode_flow.runtime.evaluate_conditions", side_effect=_condition_result
			) as evaluate,
			patch(
				"asn_module.barcode_flow.runtime.build_scan_code_metadata",
				return_value={
					"action_key": "create_purchase_invoice",
					"scan_code": "ALLOW123",
					"human_readable": "ALLOW123",
					"generation_mode": "hybrid",
				},
			) as build_metadata,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		self.assertEqual(evaluate.call_count, 2)
		build_metadata.assert_called_once()
		self.assertEqual(
			[row["action_key"] for row in result["generated_scan_codes"]], ["create_purchase_invoice"]
		)

	def test_duplicate_child_transitions_do_not_duplicate_generated_scan_codes(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			flow="FLOW-1",
			target_node="FLOW-1-NODE-received",
			field_maps=[],
		)
		flow_definition = SimpleNamespace(name="FLOW-1")
		target_doc = _FakeTargetDoc()
		action_definition = SimpleNamespace(
			name="ACT-create_purchase_invoice",
			action_key="create_purchase_invoice",
		)
		first_transition = SimpleNamespace(
			transition_key="to-invoice-a",
			source_node="FLOW-1-NODE-received",
			action=action_definition.name,
			generation_mode="immediate",
		)
		second_transition = SimpleNamespace(
			transition_key="to-invoice-b",
			source_node="FLOW-1-NODE-received",
			action=action_definition.name,
			generation_mode="hybrid",
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch(
				"asn_module.barcode_flow.runtime._get_transitions_for_source_node",
				return_value=[first_transition, second_transition],
			),
			patch(
				"asn_module.barcode_flow.runtime._get_action_definition",
				return_value=action_definition,
			),
			patch(
				"asn_module.barcode_flow.runtime.build_scan_code_metadata",
				side_effect=[
					{
						"action_key": "create_purchase_invoice",
						"scan_code": "DUPLICATE123",
						"human_readable": "DUPLICATE123",
						"generation_mode": "immediate",
					},
					{
						"action_key": "create_purchase_invoice",
						"scan_code": "DUPLICATE123",
						"human_readable": "DUPLICATE123",
						"generation_mode": "hybrid",
					},
				],
			) as build_metadata,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		self.assertEqual(build_metadata.call_count, 2)
		self.assertEqual(len(result["generated_scan_codes"]), 1)
		self.assertEqual(result["generated_scan_codes"][0]["action_key"], "create_purchase_invoice")
		self.assertEqual(result["generated_scan_codes"][0]["scan_code"], "DUPLICATE123")

	def test_custom_handler_resolves_action_binding_link_and_uses_dispatch_style_kwargs(self):
		handler = MagicMock(return_value=self._handler_result("PR-BIND"))
		action_binding = SimpleNamespace(
			name="FLOW-1-BIND-custom-receive",
			custom_handler="fake.module.handler",
		)
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=action_binding.name,
		)
		source_doc = {"doctype": "ASN", "name": "ASN-0002"}

		with (
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
			patch(
				"asn_module.barcode_flow.runtime.frappe.get_doc",
				side_effect=lambda doctype, name: action_binding if doctype == "Barcode Flow Action Binding" else None,
			),
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc=source_doc,
			)

		handler.assert_called_once()
		self.assertEqual(handler.call_args.kwargs["source_doctype"], "ASN")
		self.assertEqual(handler.call_args.kwargs["source_name"], "ASN-0002")
		payload = handler.call_args.kwargs["payload"]
		self.assertEqual(payload["transition"].action_binding, "FLOW-1-BIND-custom-receive")
		self.assertEqual(payload["action_binding"].name, "FLOW-1-BIND-custom-receive")
		self.assertEqual(result["name"], "PR-BIND")

	def test_both_mode_with_override_calls_handler_and_skips_insert(self):
		target_doc = _FakeTargetDoc()
		handler = MagicMock(return_value=self._handler_result("PR-OVERRIDE"))
		action_binding = SimpleNamespace(custom_handler="fake.module.handler", handler_override_wins=1)
		transition = SimpleNamespace(
			binding_mode="both",
			target_doctype="Purchase Receipt",
			field_maps=[],
			action_binding=action_binding,
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"doctype": "ASN", "name": "ASN-0001"},
			)

		self.assertEqual(target_doc.insert_calls, [])
		handler.assert_called_once()
		self.assertIs(handler.call_args.kwargs["payload"]["target_doc"], target_doc)
		self.assertEqual(result["name"], "PR-OVERRIDE")

	def test_both_override_with_missing_target_doctype_still_calls_handler(self):
		handler = MagicMock(return_value=self._handler_result("PR-OVERRIDE-NO-MAP"))
		transition = SimpleNamespace(
			binding_mode="both",
			target_doctype="",
			field_map_key="warehouse-map",
			binding_key="custom-receive",
		)
		flow_definition = SimpleNamespace(
			field_maps=[
				SimpleNamespace(
					map_key="warehouse-map",
					mapping_type="constant",
					target_field_path="set_warehouse",
					constant_value="WH-001",
				)
			],
			action_bindings=[
				SimpleNamespace(
					binding_key="custom-receive",
					custom_handler="fake.module.handler",
					handler_override_wins=1,
				)
			],
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc") as build_target_doc,
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"doctype": "ASN", "name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		build_target_doc.assert_not_called()
		handler.assert_called_once()
		self.assertIsNone(handler.call_args.kwargs["payload"]["target_doc"])
		self.assertEqual(result["name"], "PR-OVERRIDE-NO-MAP")

	def test_both_override_does_not_swallow_mapping_validation_errors(self):
		handler = MagicMock(return_value=self._handler_result("PR-IGNORED"))
		transition = SimpleNamespace(
			binding_mode="both",
			target_doctype="Purchase Receipt",
			field_map_key="warehouse-map",
			binding_key="custom-receive",
		)
		flow_definition = SimpleNamespace(
			field_maps=[
				SimpleNamespace(map_key="warehouse-map", mapping_type="source", target_field_path="supplier")
			],
			action_bindings=[
				SimpleNamespace(
					binding_key="custom-receive",
					custom_handler="fake.module.handler",
					handler_override_wins=1,
				)
			],
		)

		with (
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
			patch(
				"asn_module.barcode_flow.runtime.build_target_doc",
				side_effect=frappe.ValidationError("Bad mapping config"),
			),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				execute_transition_binding(
					transition=transition,
					source_doc={"doctype": "ASN", "name": "ASN-0003"},
					flow_definition=flow_definition,
				)

		self.assertIn("Bad mapping config", str(ctx.exception))
		handler.assert_not_called()

	def test_both_mode_without_override_inserts_mapped_doc(self):
		target_doc = _FakeTargetDoc()
		transition = SimpleNamespace(
			binding_mode="both",
			target_doctype="Purchase Receipt",
			field_map_key="warehouse-map",
			binding_key="custom-receive",
		)
		flow_definition = SimpleNamespace(
			field_maps=[
				SimpleNamespace(
					map_key="warehouse-map",
					mapping_type="constant",
					target_field_path="set_warehouse",
					constant_value="WH-001",
				)
			],
			action_bindings=[
				SimpleNamespace(
					binding_key="custom-receive",
					custom_handler="fake.module.handler",
					handler_override_wins=0,
				)
			],
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch("asn_module.barcode_flow.runtime.frappe.get_attr") as get_attr,
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		get_attr.assert_not_called()
		self.assertEqual(target_doc.insert_calls, [True])
		self.assertEqual(result["name"], "PR-0001")

	def test_custom_handler_mode_requires_handler_path(self):
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=SimpleNamespace(custom_handler=""),
		)

		with self.assertRaises(frappe.ValidationError) as ctx:
			execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		self.assertIn("Custom handler path is required", str(ctx.exception))

	def test_custom_handler_mode_rejects_invalid_result_contract(self):
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=SimpleNamespace(custom_handler="fake.module.handler"),
		)

		with patch(
			"asn_module.barcode_flow.runtime.frappe.get_attr",
			return_value=MagicMock(return_value={"doctype": "X"}),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		self.assertIn("Invalid handler result", str(ctx.exception))
