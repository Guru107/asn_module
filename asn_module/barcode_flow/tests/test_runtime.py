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
	def test_custom_handler_mode_calls_handler_and_returns_contract(self):
		handler_result = {
			"doctype": "Purchase Receipt",
			"name": "PR-0009",
			"url": "/app/purchase-receipt/PR-0009",
		}
		handler = MagicMock(return_value=handler_result)
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=SimpleNamespace(custom_handler="fake.module.handler"),
		)

		with (
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
			patch("asn_module.barcode_flow.runtime.build_target_doc") as build_target_doc,
		):
			result = execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		build_target_doc.assert_not_called()
		handler.assert_called_once()
		self.assertEqual(result, handler_result)

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

	def test_both_mode_with_override_calls_handler_and_skips_insert(self):
		target_doc = _FakeTargetDoc()
		handler_result = {
			"doctype": "Purchase Receipt",
			"name": "PR-OVERRIDE",
			"url": "/app/purchase-receipt/PR-OVERRIDE",
		}
		handler = MagicMock(return_value=handler_result)
		transition = SimpleNamespace(
			binding_mode="both",
			target_doctype="Purchase Receipt",
			field_maps=[],
			action_binding=SimpleNamespace(
				custom_handler="fake.module.handler",
				handler_override_wins=1,
			),
		)

		with (
			patch("asn_module.barcode_flow.runtime.build_target_doc", return_value=target_doc),
			patch("asn_module.barcode_flow.runtime.frappe.get_attr", return_value=handler),
		):
			result = execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		self.assertEqual(target_doc.insert_calls, [])
		handler.assert_called_once()
		self.assertIs(handler.call_args.kwargs["target_doc"], target_doc)
		self.assertEqual(result, handler_result)

	def test_both_override_with_missing_target_doctype_still_calls_handler(self):
		handler_result = {
			"doctype": "Purchase Receipt",
			"name": "PR-OVERRIDE-NO-MAP",
			"url": "/app/purchase-receipt/PR-OVERRIDE-NO-MAP",
		}
		handler = MagicMock(return_value=handler_result)
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
			result = execute_transition_binding(transition=transition, source_doc={"name": "ASN-0001"})

		build_target_doc.assert_not_called()
		handler.assert_called_once()
		self.assertIsNone(handler.call_args.kwargs["target_doc"])
		self.assertEqual(result, handler_result)

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
