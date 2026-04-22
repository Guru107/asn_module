import importlib

import frappe
from frappe.exceptions import UniqueValidationError
from frappe.tests.utils import FrappeTestCase


class TestBarcodeFlowSchema(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for doctype in [
			"barcode_flow_scope",
			"barcode_flow_node",
			"barcode_flow_transition",
			"barcode_flow_condition",
			"barcode_flow_field_map",
			"barcode_flow_action_binding",
			"barcode_flow_definition",
			"qr_action_definition",
		]:
			frappe.reload_doc("asn_module", "doctype", doctype)

	def make_flow(self, flow_name: str | None = None, **overrides):
		payload = {
			"doctype": "Barcode Flow Definition",
			"flow_name": flow_name or f"Flow-{frappe.generate_hash(length=8)}",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_node(self, *, flow: str, node_key: str = "scan", **overrides):
		payload = {
			"doctype": "Barcode Flow Node",
			"flow": flow,
			"node_key": node_key,
			"label": "Scan",
			"node_type": "State",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_condition(self, *, flow: str, condition_key: str = "has-warehouse", **overrides):
		payload = {
			"doctype": "Barcode Flow Condition",
			"flow": flow,
			"condition_key": condition_key,
			"scope": "header",
			"field_path": "header.set_warehouse",
			"operator": "eq",
			"value": "Stores - _TC",
			"aggregate_fn": "",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_field_map(self, *, flow: str, map_key: str = "warehouse-map", **overrides):
		payload = {
			"doctype": "Barcode Flow Field Map",
			"flow": flow,
			"map_key": map_key,
			"mapping_type": "source",
			"source_field_path": "header.set_warehouse",
			"target_field_path": "target.set_warehouse",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_action_binding(self, *, flow: str, binding_key: str = "handler-binding", **overrides):
		payload = {
			"doctype": "Barcode Flow Action Binding",
			"flow": flow,
			"binding_key": binding_key,
			"trigger_event": "custom_handler",
			"action": self.make_action_definition().name,
			"custom_handler": "asn_module.handlers.purchase_receipt.create_from_asn",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_action_definition(self, action_key: str | None = None, **overrides):
		payload = {
			"doctype": "QR Action Definition",
			"action_key": action_key or f"action-{frappe.generate_hash(length=8)}",
			"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
			"source_doctype": "ASN",
			"allowed_roles": "Stock User",
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def make_transition(
		self,
		*,
		flow: str,
		source_node: str,
		target_node: str,
		binding_mode: str = "mapping",
		transition_key: str | None = None,
		**overrides,
	):
		payload = {
			"doctype": "Barcode Flow Transition",
			"flow": flow,
			"transition_key": transition_key or f"transition-{frappe.generate_hash(length=6)}",
			"generation_mode": "runtime",
			"source_node": source_node,
			"target_node": target_node,
			"action": self.make_action_definition().name,
			"binding_mode": binding_mode,
		}
		payload.update(overrides)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def test_definition_retains_only_scopes_table(self):
		meta = frappe.get_meta("Barcode Flow Definition")
		table_fields = {field.fieldname for field in meta.fields if field.fieldtype == "Table"}

		assert table_fields == {"scopes"}

	def test_transition_references_links_not_key_data_fields(self):
		meta = frappe.get_meta("Barcode Flow Transition")

		assert meta.get_field("source_node").fieldtype == "Link"
		assert meta.get_field("source_node").options == "Barcode Flow Node"
		assert meta.get_field("target_node").fieldtype == "Link"
		assert meta.get_field("condition").options == "Barcode Flow Condition"
		assert meta.get_field("field_map").options == "Barcode Flow Field Map"
		assert meta.get_field("action_binding").options == "Barcode Flow Action Binding"
		assert meta.get_field("action").options == "QR Action Definition"
		assert meta.get_field("target_doctype").fieldtype == "Link"
		assert meta.get_field("target_doctype").options == "DocType"

		assert meta.get_field("source_node_key") is None
		assert meta.get_field("target_node_key") is None
		assert meta.get_field("condition_key") is None
		assert meta.get_field("field_map_key") is None
		assert meta.get_field("binding_key") is None
		assert meta.get_field("action_key") is None

	def test_node_requires_flow_link(self):
		node = frappe.get_doc(
			{"doctype": "Barcode Flow Node", "node_key": "scan", "label": "Scan", "node_type": "State"}
		)

		with self.assertRaises(frappe.ValidationError):
			node.insert(ignore_permissions=True)

	def test_standalone_entities_require_flow_link(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Condition",
					"condition_key": "has-warehouse",
					"scope": "header",
					"field_path": "header.set_warehouse",
					"operator": "eq",
					"value": "Main Warehouse",
				}
			).insert(ignore_permissions=True)

	def test_node_key_must_be_unique_within_flow(self):
		flow = self.make_flow()
		self.make_node(flow=flow.name, node_key="scan")

		with self.assertRaises(UniqueValidationError):
			self.make_node(flow=flow.name, node_key="scan", label="Scan Again")

	def test_node_key_can_repeat_across_flows(self):
		first_flow = self.make_flow()
		second_flow = self.make_flow()

		first_node = self.make_node(flow=first_flow.name, node_key="scan")
		second_node = self.make_node(flow=second_flow.name, node_key="scan")

		assert first_node.name != second_node.name

	def test_condition_key_must_be_unique_within_flow(self):
		flow = self.make_flow()
		self.make_condition(flow=flow.name, condition_key="has-warehouse")

		with self.assertRaises(UniqueValidationError):
			self.make_condition(flow=flow.name, condition_key="has-warehouse", value="Main Warehouse")

	def test_condition_key_can_repeat_across_flows(self):
		first_flow = self.make_flow()
		second_flow = self.make_flow()

		first_condition = self.make_condition(flow=first_flow.name, condition_key="has-warehouse")
		second_condition = self.make_condition(flow=second_flow.name, condition_key="has-warehouse")

		assert first_condition.name != second_condition.name

	def test_field_map_key_must_be_unique_within_flow(self):
		flow = self.make_flow()
		self.make_field_map(flow=flow.name, map_key="warehouse-map")

		with self.assertRaises(UniqueValidationError):
			self.make_field_map(flow=flow.name, map_key="warehouse-map", target_field_path="target.other_field")

	def test_field_map_key_can_repeat_across_flows(self):
		first_flow = self.make_flow()
		second_flow = self.make_flow()

		first_map = self.make_field_map(flow=first_flow.name, map_key="warehouse-map")
		second_map = self.make_field_map(flow=second_flow.name, map_key="warehouse-map")

		assert first_map.name != second_map.name

	def test_action_binding_key_must_be_unique_within_flow(self):
		flow = self.make_flow()
		self.make_action_binding(flow=flow.name, binding_key="custom-receive")

		with self.assertRaises(UniqueValidationError):
			self.make_action_binding(flow=flow.name, binding_key="custom-receive")

	def test_action_binding_key_can_repeat_across_flows(self):
		first_flow = self.make_flow()
		second_flow = self.make_flow()

		first_binding = self.make_action_binding(flow=first_flow.name, binding_key="custom-receive")
		second_binding = self.make_action_binding(flow=second_flow.name, binding_key="custom-receive")

		assert first_binding.name != second_binding.name

	def test_transition_key_must_be_unique_within_flow(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name, map_key="warehouse-map")
		transition_key = "scan-to-received"

		self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			transition_key=transition_key,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaises(UniqueValidationError):
			self.make_transition(
				flow=flow.name,
				source_node=source_node.name,
				target_node=target_node.name,
				transition_key=transition_key,
				field_map=field_map.name,
				target_doctype="Purchase Receipt",
			)

	def test_transition_key_can_repeat_across_flows(self):
		transition_key = "scan-to-received"
		first_flow = self.make_flow()
		second_flow = self.make_flow()

		first_source = self.make_node(flow=first_flow.name, node_key="scan")
		first_target = self.make_node(flow=first_flow.name, node_key="received", label="Received")
		first_map = self.make_field_map(flow=first_flow.name, map_key="warehouse-map")

		second_source = self.make_node(flow=second_flow.name, node_key="scan")
		second_target = self.make_node(flow=second_flow.name, node_key="received", label="Received")
		second_map = self.make_field_map(flow=second_flow.name, map_key="warehouse-map")

		first_transition = self.make_transition(
			flow=first_flow.name,
			source_node=first_source.name,
			target_node=first_target.name,
			transition_key=transition_key,
			field_map=first_map.name,
			target_doctype="Purchase Receipt",
		)
		second_transition = self.make_transition(
			flow=second_flow.name,
			source_node=second_source.name,
			target_node=second_target.name,
			transition_key=transition_key,
			field_map=second_map.name,
			target_doctype="Purchase Receipt",
		)

		assert first_transition.name != second_transition.name

	def test_index_patch_execute_is_idempotent_and_verified(self):
		patch = importlib.import_module(
			"asn_module.patches.post_model_sync.2026_04_21_add_barcode_flow_indexes"
		)

		patch.execute()
		patch.execute()
		verified = patch.verify_indexes()

		assert all(verified.values())

	def test_transition_mapping_mode_requires_field_map_and_target_doctype(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")

		with self.assertRaises(frappe.ValidationError):
			self.make_transition(flow=flow.name, source_node=source_node.name, target_node=target_node.name)

	def test_transition_rejects_cross_flow_nodes(self):
		flow = self.make_flow()
		other_flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		cross_flow_target = self.make_node(flow=other_flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"Target Node must belong to flow",
		):
			self.make_transition(
				flow=flow.name,
				source_node=source_node.name,
				target_node=cross_flow_target.name,
				field_map=field_map.name,
				target_doctype="Purchase Receipt",
			)

	def test_transition_allows_same_flow_mapping_insert(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)

		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		assert transition.name

	def test_transition_custom_handler_mode_requires_custom_handler_binding(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		binding = self.make_action_binding(
			flow=flow.name,
			binding_key=f"binding-{frappe.generate_hash(length=6)}",
			trigger_event="On Enter Node",
			target_node=source_node.name,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_transition(
				flow=flow.name,
				source_node=source_node.name,
				target_node=target_node.name,
				binding_mode="custom_handler",
				action_binding=binding.name,
			)

	def test_transition_both_mode_requires_mapping_and_custom_handler_contracts(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)

		with self.assertRaises(frappe.ValidationError):
			self.make_transition(
				flow=flow.name,
				source_node=source_node.name,
				target_node=target_node.name,
				binding_mode="both",
				field_map=field_map.name,
				target_doctype="Purchase Receipt",
			)

	def test_transition_both_with_override_allows_missing_target_doctype(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		binding = self.make_action_binding(
			flow=flow.name,
			binding_key=f"binding-{frappe.generate_hash(length=6)}",
			handler_override_wins=1,
		)

		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			binding_mode="both",
			field_map=field_map.name,
			action_binding=binding.name,
			target_doctype="",
		)

		assert transition.name

	def test_action_binding_custom_handler_trigger_requires_handler_and_no_targets(self):
		flow = self.make_flow()
		node = self.make_node(flow=flow.name)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Action Binding",
					"flow": flow.name,
					"binding_key": f"binding-{frappe.generate_hash(length=6)}",
					"trigger_event": "custom_handler",
					"target_node": node.name,
					"action": self.make_action_definition().name,
				}
			).insert(ignore_permissions=True)

	def test_action_binding_custom_handler_trigger_allows_same_flow_binding(self):
		flow = self.make_flow()

		binding = self.make_action_binding(flow=flow.name, binding_key=f"binding-{frappe.generate_hash(length=6)}")

		assert binding.name

	def test_action_binding_node_triggers_require_target_node(self):
		flow = self.make_flow()

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Action Binding",
					"flow": flow.name,
					"binding_key": f"binding-{frappe.generate_hash(length=6)}",
					"trigger_event": "On Enter Node",
					"action": self.make_action_definition().name,
				}
			).insert(ignore_permissions=True)

	def test_action_binding_node_trigger_rejects_cross_flow_node(self):
		flow = self.make_flow()
		other_flow = self.make_flow()
		cross_flow_node = self.make_node(flow=other_flow.name)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"Target Node must belong to flow",
		):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Action Binding",
					"flow": flow.name,
					"binding_key": f"binding-{frappe.generate_hash(length=6)}",
					"trigger_event": "On Enter Node",
					"target_node": cross_flow_node.name,
					"action": self.make_action_definition().name,
				}
			).insert(ignore_permissions=True)

	def test_action_binding_node_trigger_allows_same_flow_node(self):
		flow = self.make_flow()
		node = self.make_node(flow=flow.name)

		binding = frappe.get_doc(
			{
				"doctype": "Barcode Flow Action Binding",
				"flow": flow.name,
				"binding_key": f"binding-{frappe.generate_hash(length=6)}",
				"trigger_event": "On Enter Node",
				"target_node": node.name,
				"action": self.make_action_definition().name,
			}
		).insert(ignore_permissions=True)

		assert binding.name

	def test_action_binding_transition_trigger_requires_target_transition(self):
		flow = self.make_flow()

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Action Binding",
					"flow": flow.name,
					"binding_key": f"binding-{frappe.generate_hash(length=6)}",
					"trigger_event": "On Transition",
					"action": self.make_action_definition().name,
				}
			).insert(ignore_permissions=True)

	def test_action_binding_transition_trigger_rejects_cross_flow_transition(self):
		flow = self.make_flow()
		other_flow = self.make_flow()
		other_source_node = self.make_node(flow=other_flow.name, node_key="start")
		other_target_node = self.make_node(flow=other_flow.name, node_key="done", label="Done")
		other_field_map = self.make_field_map(flow=other_flow.name)
		other_transition = self.make_transition(
			flow=other_flow.name,
			source_node=other_source_node.name,
			target_node=other_target_node.name,
			field_map=other_field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"Target Transition must belong to flow",
		):
			frappe.get_doc(
				{
					"doctype": "Barcode Flow Action Binding",
					"flow": flow.name,
					"binding_key": f"binding-{frappe.generate_hash(length=6)}",
					"trigger_event": "On Transition",
					"target_transition": other_transition.name,
					"action": self.make_action_definition().name,
				}
			).insert(ignore_permissions=True)

	def test_action_binding_transition_trigger_allows_same_flow_transition(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		binding = frappe.get_doc(
			{
				"doctype": "Barcode Flow Action Binding",
				"flow": flow.name,
				"binding_key": f"binding-{frappe.generate_hash(length=6)}",
				"trigger_event": "On Transition",
				"target_transition": transition.name,
				"action": self.make_action_definition().name,
			}
		).insert(ignore_permissions=True)

		assert binding.name

	def test_delete_node_blocked_by_transition_source_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			source_node.delete()

	def test_delete_node_blocked_by_transition_target_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			target_node.delete()

	def test_delete_node_blocked_by_action_binding_target_node_reference(self):
		flow = self.make_flow()
		node = self.make_node(flow=flow.name, node_key="scan")
		binding = frappe.get_doc(
			{
				"doctype": "Barcode Flow Action Binding",
				"flow": flow.name,
				"binding_key": f"binding-{frappe.generate_hash(length=6)}",
				"trigger_event": "On Enter Node",
				"target_node": node.name,
				"action": self.make_action_definition().name,
			}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, binding.name):
			node.delete()

	def test_delete_condition_blocked_by_transition_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		condition = self.make_condition(flow=flow.name)
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			condition=condition.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			condition.delete()

	def test_delete_field_map_blocked_by_transition_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			field_map.delete()

	def test_delete_action_binding_blocked_by_transition_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		binding = self.make_action_binding(flow=flow.name, binding_key="custom-receive")
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			binding_mode="both",
			field_map=field_map.name,
			action_binding=binding.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			binding.delete()

	def test_delete_transition_blocked_by_action_binding_target_transition_reference(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)
		binding = frappe.get_doc(
			{
				"doctype": "Barcode Flow Action Binding",
				"flow": flow.name,
				"binding_key": f"binding-{frappe.generate_hash(length=6)}",
				"trigger_event": "On Transition",
				"target_transition": transition.name,
				"action": self.make_action_definition().name,
			}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, binding.name):
			transition.delete()

	def test_delete_qr_action_definition_blocked_by_transition_reference(self):
		flow = self.make_flow()
		action = self.make_action_definition(action_key=f"action-{frappe.generate_hash(length=6)}")
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			action=action.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		with self.assertRaisesRegex(frappe.ValidationError, transition.name):
			action.delete()

	def test_delete_qr_action_definition_blocked_by_action_binding_reference(self):
		flow = self.make_flow()
		action = self.make_action_definition(action_key=f"action-{frappe.generate_hash(length=6)}")
		binding = self.make_action_binding(
			flow=flow.name,
			binding_key=f"binding-{frappe.generate_hash(length=6)}",
			action=action.name,
		)

		with self.assertRaisesRegex(frappe.ValidationError, binding.name):
			action.delete()

	def test_delete_qr_action_definition_succeeds_after_references_are_removed(self):
		flow = self.make_flow()
		action = self.make_action_definition(action_key=f"action-{frappe.generate_hash(length=6)}")
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name, map_key=f"map-{frappe.generate_hash(length=6)}")
		binding = self.make_action_binding(
			flow=flow.name,
			binding_key=f"binding-{frappe.generate_hash(length=6)}",
			action=action.name,
		)
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			action=action.name,
			action_binding=binding.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		transition.delete()
		binding.delete()
		action.delete()

		assert not frappe.db.exists("QR Action Definition", action.name)

	def test_delete_unused_field_map_succeeds(self):
		flow = self.make_flow()
		field_map = self.make_field_map(flow=flow.name, map_key=f"unused-map-{frappe.generate_hash(length=6)}")

		field_map.delete()

		assert not frappe.db.exists("Barcode Flow Field Map", field_map.name)

	def test_delete_node_succeeds_after_transition_reference_is_detached(self):
		flow = self.make_flow()
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		field_map = self.make_field_map(flow=flow.name, map_key=f"map-{frappe.generate_hash(length=6)}")
		transition = self.make_transition(
			flow=flow.name,
			source_node=source_node.name,
			target_node=target_node.name,
			field_map=field_map.name,
			target_doctype="Purchase Receipt",
		)

		transition.delete()
		source_node.delete()

		assert not frappe.db.exists("Barcode Flow Node", source_node.name)

	def test_deterministic_semantic_autoname_for_node(self):
		flow = self.make_flow(flow_name=f"Inbound-ACME-Node-{frappe.generate_hash(length=6)}")
		node = self.make_node(flow=flow.name, node_key="scan")

		assert node.name == f"FLOW-{flow.name}-NODE-scan"

	def test_deterministic_semantic_autoname_for_flow_entities(self):
		flow = self.make_flow(flow_name=f"Inbound-ACME-Graph-{frappe.generate_hash(length=6)}")
		source_node = self.make_node(flow=flow.name, node_key="scan")
		target_node = self.make_node(flow=flow.name, node_key="received", label="Received")
		condition = self.make_condition(flow=flow.name, condition_key="has-warehouse")
		field_map = self.make_field_map(flow=flow.name, map_key="warehouse-map")
		action = self.make_action_definition(action_key=f"create_purchase_receipt_{frappe.generate_hash(length=6)}")
		binding = self.make_action_binding(flow=flow.name, binding_key="custom-receive", action=action.name)
		transition = frappe.get_doc(
			{
				"doctype": "Barcode Flow Transition",
				"flow": flow.name,
				"transition_key": "scan-to-received",
				"generation_mode": "runtime",
				"source_node": source_node.name,
				"target_node": target_node.name,
				"condition": condition.name,
				"field_map": field_map.name,
				"action_binding": binding.name,
				"action": action.name,
				"binding_mode": "both",
				"target_doctype": "Purchase Receipt",
			}
		).insert(ignore_permissions=True)

		assert condition.name == f"FLOW-{flow.name}-COND-has-warehouse"
		assert field_map.name == f"FLOW-{flow.name}-MAP-warehouse-map"
		assert binding.name == f"FLOW-{flow.name}-BIND-custom-receive"
		assert transition.name == f"FLOW-{flow.name}-TRANS-scan-to-received"

	def test_deterministic_semantic_autoname_for_qr_action_definition(self):
		action_key = f"create_purchase_receipt_{frappe.generate_hash(length=6)}"
		action = self.make_action_definition(action_key=action_key)

		assert action.name == f"ACT-{action_key}"
