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
if not hasattr(frappe_stub, "get_attr"):
	frappe_stub.get_attr = lambda _path: None
if not hasattr(frappe_stub, "get_doc"):
	frappe_stub.get_doc = lambda payload: payload

import frappe

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
		self.assertEqual(result, self._handler_result())

	def test_mapping_mode_builds_and_inserts_target_doc(self):
		transition = SimpleNamespace(
			binding_mode="mapping",
			target_doctype="Purchase Receipt",
			field_maps=[SimpleNamespace(mapping_type="constant", target_field_path="supplier", constant_value="SUP-001")],
		)
		target_doc = _FakeTargetDoc()

		with patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc) as build_target_doc:
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

		with patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc) as build_target_doc:
			execute_transition_binding(
				transition=transition,
				source_doc={"name": "ASN-0001"},
				flow_definition=flow_definition,
			)

		self.assertEqual(build_target_doc.call_args.kwargs["target_doctype"], "Purchase Receipt")
		resolved_mappings = build_target_doc.call_args.kwargs["mappings"]
		self.assertEqual(len(resolved_mappings), 1)
		self.assertEqual(resolved_mappings[0].map_key, "warehouse-map")

	def test_custom_handler_resolves_binding_by_key_and_uses_dispatch_style_kwargs(self):
		handler = MagicMock(return_value=self._handler_result("PR-BIND"))
		transition = SimpleNamespace(binding_mode="custom_handler", binding_key="custom-receive")
		flow_definition = SimpleNamespace(
			action_bindings=[
				SimpleNamespace(
					binding_key="custom-receive",
					custom_handler="fake.module.handler",
				)
			]
		)
		source_doc = {"doctype": "ASN", "name": "ASN-0002"}

		with patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler):
			result = execute_transition_binding(
				transition=transition,
				source_doc=source_doc,
				flow_definition=flow_definition,
			)

		handler.assert_called_once()
		self.assertEqual(handler.call_args.kwargs["source_doctype"], "ASN")
		self.assertEqual(handler.call_args.kwargs["source_name"], "ASN-0002")
		payload = handler.call_args.kwargs["payload"]
		self.assertEqual(payload["transition"].binding_key, "custom-receive")
		self.assertEqual(payload["action_binding"].binding_key, "custom-receive")
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
			field_maps=[],
			action_binding=SimpleNamespace(
				custom_handler="fake.module.handler",
				handler_override_wins=1,
			),
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc") as build_target_doc,
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc={"doctype": "ASN", "name": "ASN-0001"},
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
			field_maps=[SimpleNamespace(map_key="warehouse-map", mapping_type="source", target_field_path="supplier")],
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
			field_maps=[],
			action_binding=SimpleNamespace(
				custom_handler="fake.module.handler",
				handler_override_wins=0,
			),
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch("asn_module.barcode_flow.runtime.frappe.get_attr") as get_attr,
		):
			result = execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

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

		with patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=MagicMock(return_value={"doctype": "X"})):
			with self.assertRaises(frappe.ValidationError) as ctx:
				execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		self.assertIn("Invalid handler result", str(ctx.exception))
