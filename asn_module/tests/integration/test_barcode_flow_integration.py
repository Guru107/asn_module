from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
	real_asn_attachment_context,
)
from asn_module.barcode_flow.runtime import execute_transition_binding
from asn_module.qr_engine import dispatch as dispatch_module
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.fixtures import (
	cleanup_dispatch_flow_fixtures,
	ensure_integration_user,
	ensure_scoped_flow_route_fixtures,
	integration_user_context,
)
from asn_module.utils.test_setup import before_tests


class TestBarcodeFlowIntegration(FrappeTestCase):
	def test_execute_transition_binding_returns_child_scan_codes_for_hybrid_and_immediate(self):
		transition = SimpleNamespace(
			binding_mode="custom_handler",
			action_binding=SimpleNamespace(custom_handler="asn_module.tests.integration.fake_handler"),
			target_node_key="received",
		)
		flow_definition = SimpleNamespace(
			transitions=[
				SimpleNamespace(
					transition_key="child-hybrid",
					source_node_key="received",
					action_key="create_purchase_invoice",
					generation_mode="hybrid",
				),
				SimpleNamespace(
					transition_key="child-immediate",
					source_node_key="received",
					action_key="confirm_putaway",
					generation_mode="immediate",
				),
				SimpleNamespace(
					transition_key="child-runtime",
					source_node_key="received",
					action_key="create_stock_transfer",
					generation_mode="runtime",
				),
			]
		)
		source_doc = {"doctype": "DocType", "name": "QR Action Registry"}
		target_name = "ToDo"

		with patch(
			"asn_module.barcode_flow.runtime._run_custom_handler",
			return_value={
				"doctype": "DocType",
				"name": target_name,
				"url": f"/app/doctype/{target_name}",
			},
		):
			result = execute_transition_binding(
				transition=transition,
				source_doc=source_doc,
				flow_definition=flow_definition,
			)

		self.assertEqual(result["doctype"], "DocType")
		self.assertEqual(result["name"], target_name)
		self.assertEqual(result["url"], f"/app/doctype/{target_name}")

		generated = result["generated_scan_codes"]
		self.assertEqual(len(generated), 2)
		self.assertEqual({row["action_key"] for row in generated}, {"create_purchase_invoice", "confirm_putaway"})
		self.assertNotIn("create_stock_transfer", {row["action_key"] for row in generated})
		self.assertEqual(
			{row["generation_mode"] for row in generated},
			{"hybrid", "immediate"},
		)
		for row in generated:
			self.assertTrue(row["scan_code"])
			self.assertTrue(row["human_readable"])

		for action_key in ("create_purchase_invoice", "confirm_putaway"):
			self.assertTrue(
				frappe.db.exists(
					"Scan Code",
					{
						"action_key": action_key,
						"source_doctype": "DocType",
						"source_name": target_name,
						"status": "Active",
					},
				)
			)

		self.assertFalse(
			frappe.db.exists(
				"Scan Code",
				{
					"action_key": "create_stock_transfer",
					"source_doctype": "DocType",
					"source_name": target_name,
					"status": "Active",
				},
			)
		)


def _simulate_gate_in_handler(*, source_doctype: str, source_name: str, payload: dict) -> dict:
	todo = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": f"Gate-In simulation for {source_doctype} {source_name}",
		}
	)
	todo.insert(ignore_permissions=True)
	return {
		"doctype": "ToDo",
		"name": todo.name,
		"url": f"/app/todo/{todo.name}",
		"message": payload.get("transition").transition_key,
	}


class TestBarcodeFlowScopedRoutingIntegration(FrappeTestCase):
	@classmethod
	def _snapshot_registry_actions(cls) -> list[dict]:
		reg = frappe.get_doc("QR Action Registry")
		return [
			{
				"action_key": row.action_key,
				"handler_method": row.handler_method,
				"source_doctype": row.source_doctype,
				"allowed_roles": row.allowed_roles,
			}
			for row in (reg.actions or [])
		]

	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		cls._registry_snapshot = cls._snapshot_registry_actions()
		register_actions()
		ensure_integration_user()
		cls._flow_fixture_prefix = "IT-Dispatch-Flow-ScopedRoutingIntegration"
		cleanup_dispatch_flow_fixtures(flow_name_prefix=cls._flow_fixture_prefix)
		cls._scoped_routes = ensure_scoped_flow_route_fixtures(
			flow_name_prefix=cls._flow_fixture_prefix,
			source_doctype="ASN",
			action_key="create_purchase_receipt",
			gate_handler="asn_module.tests.integration.test_barcode_flow_integration._simulate_gate_in_handler",
		)

	@classmethod
	def tearDownClass(cls):
		cleanup_dispatch_flow_fixtures(flow_name_prefix=cls._flow_fixture_prefix)
		reg = frappe.get_doc("QR Action Registry")
		reg.set("actions", [])
		for row in cls._registry_snapshot:
			reg.append("actions", row)
		reg.save(ignore_permissions=True)
		super().tearDownClass()

	def _make_submitted_asn(self, *, warehouse: str) -> frappe.model.document.Document:
		with integration_user_context():
			purchase_order = create_purchase_order(qty=2, warehouse=warehouse)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"SCOPED-{frappe.generate_hash(length=8)}",
				qty=2,
			)
			asn.insert(ignore_permissions=True)
			with real_asn_attachment_context():
				asn.submit()
			asn.reload()
			return asn

	def _dispatch_asn(self, *, asn_name: str, device_info: str) -> dict:
		with integration_user_context():
			scan_code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn_name)
			return dispatch(code=scan_code, device_info=device_info)

	def _latest_scan_log(self, *, asn_name: str, device_info: str) -> dict:
		return frappe.get_all(
			"Scan Log",
			filters={
				"action": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": asn_name,
				"result": "Success",
				"device_info": device_info,
			},
			fields=[
				"barcode_flow_definition",
				"barcode_flow_transition",
				"scope_resolution_key",
				"result_doctype",
				"result_name",
			],
			order_by="creation desc",
			limit=1,
		)[0]

	def test_scope_routes_asn_scan_to_gate_like_step_first(self):
		route = self._scoped_routes["gate_like"]
		asn = self._make_submitted_asn(warehouse=route["context"]["warehouse"])
		device_info = f"it-gate-{frappe.generate_hash(length=6)}"
		derived_context = dispatch_module._build_flow_resolution_context(asn)
		self.assertEqual(derived_context["company"], route["context"]["company"])
		self.assertEqual(derived_context["warehouse"], route["context"]["warehouse"])

		result = self._dispatch_asn(
			asn_name=asn.name,
			device_info=device_info,
		)
		self.assertTrue(result.get("success"))
		self.assertEqual(result.get("doctype"), "ToDo")

		log = self._latest_scan_log(asn_name=asn.name, device_info=device_info)
		self.assertEqual(log["barcode_flow_definition"], route["flow_name"])
		self.assertEqual(log["barcode_flow_transition"], route["transition_key"])
		self.assertEqual(log["scope_resolution_key"], route["scope_key"])
		self.assertEqual(log["result_doctype"], "ToDo")

	def test_scope_routes_asn_scan_directly_to_purchase_receipt_when_gate_scope_misses(self):
		route = self._scoped_routes["direct_pr"]
		gate_route = self._scoped_routes["gate_like"]
		asn = self._make_submitted_asn(warehouse=route["context"]["warehouse"])
		device_info = f"it-direct-{frappe.generate_hash(length=6)}"
		derived_context = dispatch_module._build_flow_resolution_context(asn)
		self.assertEqual(derived_context["company"], route["context"]["company"])
		self.assertEqual(derived_context["warehouse"], route["context"]["warehouse"])
		self.assertNotEqual(derived_context["warehouse"], gate_route["context"]["warehouse"])

		result = self._dispatch_asn(
			asn_name=asn.name,
			device_info=device_info,
		)
		self.assertTrue(result.get("success"))
		self.assertEqual(result.get("doctype"), "Purchase Receipt")
		self.assertEqual(frappe.get_doc("Purchase Receipt", result["name"]).docstatus, 0)

		log = self._latest_scan_log(asn_name=asn.name, device_info=device_info)
		self.assertEqual(log["barcode_flow_definition"], route["flow_name"])
		self.assertEqual(log["barcode_flow_transition"], route["transition_key"])
		self.assertEqual(log["scope_resolution_key"], route["scope_key"])
		self.assertEqual(log["result_doctype"], "Purchase Receipt")
