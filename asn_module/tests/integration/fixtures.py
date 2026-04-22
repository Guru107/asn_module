"""Shared fixtures for integration tests: real users and session switching.

Golden-path dispatch tests use a user with **Stock User** + **Accounts User** so
``frappe.get_roles()`` satisfies both PR and PI registry rows without patching.

Do **not** add System Manager to this user — it would bypass real permission checks.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from asn_module.barcode_flow.resolver import resolve_flow_with_scope
from asn_module.setup_actions import get_canonical_actions

# Roles required together for create_purchase_receipt + create_purchase_invoice dispatch.
DEFAULT_INTEGRATION_ROLES = (
	"Stock User",
	"Stock Manager",
	"Accounts User",
	"Accounts Manager",
)

INTEGRATION_USER_EMAIL = "asn.integration.ops@asn-module.test"
SCOPED_GATE_WAREHOUSE_NAME = "_Test ASN Scoped Gate Warehouse"
SCOPED_DIRECT_WAREHOUSE_NAME = "_Test ASN Scoped Direct Warehouse"


def ensure_integration_user(
	email: str = INTEGRATION_USER_EMAIL,
	roles: tuple[str, ...] = DEFAULT_INTEGRATION_ROLES,
) -> str:
	"""Create or update a User with the given Frappe roles. Returns email."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "ASN Integration",
				"send_welcome_email": 0,
				"enabled": 1,
				"new_password": "integration-test-pw",
			}
		)
		user.insert(ignore_permissions=True)

	desired = set(roles)
	existing = {r.role for r in (user.roles or [])}
	if existing != desired:
		user.set("roles", [])
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	return email


def ensure_dispatch_flow_fixtures(*, flow_name_prefix: str = "IT-Dispatch-Flow") -> dict[str, dict[str, str]]:
	"""Seed active flow definitions for canonical dispatch actions (custom_handler binding mode)."""
	action_rows = get_canonical_actions()
	actions_by_source: dict[str, list[dict]] = {}
	for row in action_rows:
		actions_by_source.setdefault(row["source_doctype"], []).append(row)

	mapping: dict[str, dict[str, str]] = {}
	for source_doctype, rows in actions_by_source.items():
		flow_name = f"{flow_name_prefix}::{source_doctype}"
		flow = _upsert_flow_definition(
			flow_name=flow_name,
			source_doctype=source_doctype,
			action_rows=sorted(rows, key=lambda item: item["action_key"]),
		)
		for row in rows:
			action_key = row["action_key"]
			transition = flow["transitions"][action_key]
			binding = flow["bindings"][action_key]
			mapping[action_key] = {
				"flow_name": flow["definition"].name,
				"transition_key": _transition_key_for_action(action_key),
				"transition_name": transition.name,
				"binding_name": binding.name,
				"action_name": transition.action,
				"source_node_name": flow["nodes"]["scan"].name,
				"target_node_name": flow["nodes"]["handled"].name,
			}

	return mapping


def ensure_scoped_flow_route_fixtures(
	*,
	flow_name_prefix: str = "IT-Dispatch-Flow-Scoped",
	source_doctype: str,
	action_key: str,
	gate_handler: str,
) -> dict[str, dict[str, object]]:
	"""Create scoped flow fixtures with disjoint resolver scopes for one action route."""
	action_rows = get_canonical_actions()
	action_row = next(
		(
			row
			for row in action_rows
			if row["action_key"] == action_key and row["source_doctype"] == source_doctype
		),
		None,
	)
	if not action_row:
		raise frappe.ValidationError(
			f"No canonical action row found for action_key={action_key}, source_doctype={source_doctype}"
		)

	gate_scope_company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not gate_scope_company:
		raise frappe.ValidationError("No Company records exist for scoped flow fixture setup")
	scoped_warehouses = ensure_scoped_test_warehouses(company=gate_scope_company)
	gate_scope_warehouse = scoped_warehouses["gate"]
	direct_scope_warehouse = scoped_warehouses["direct"]

	gate_flow_name = f"{flow_name_prefix}::gate::{source_doctype}::{action_key}"
	direct_flow_name = f"{flow_name_prefix}::direct::{source_doctype}::{action_key}"
	gate_transition_key = f"transition-{action_key}-gate-like"
	direct_transition_key = f"transition-{action_key}-direct-pr"

	_upsert_scoped_single_action_flow_definition(
		flow_name=gate_flow_name,
		source_doctype=source_doctype,
		action_key=action_key,
		handler_method=gate_handler,
		scope_key="gate-like-scope",
		scope_company=gate_scope_company,
		scope_warehouse=gate_scope_warehouse,
		scope_supplier_type=None,
		transition_key=gate_transition_key,
		scope_priority=300,
	)
	_upsert_scoped_single_action_flow_definition(
		flow_name=direct_flow_name,
		source_doctype=source_doctype,
		action_key=action_key,
		handler_method=action_row["handler_method"],
		scope_key="direct-pr-scope",
		scope_company=gate_scope_company,
		scope_warehouse=direct_scope_warehouse,
		scope_supplier_type=None,
		transition_key=direct_transition_key,
		scope_priority=200,
	)

	return {
		"gate_like": {
			"flow_name": gate_flow_name,
			"transition_key": gate_transition_key,
			"transition_name": f"FLOW-{gate_flow_name}-TRANS-{gate_transition_key}",
			"binding_name": f"FLOW-{gate_flow_name}-BIND-{_binding_key_for_action(action_key)}",
			"source_node_name": f"FLOW-{gate_flow_name}-NODE-scan",
			"target_node_name": f"FLOW-{gate_flow_name}-NODE-handled",
			"scope_key": "gate-like-scope",
			"context": {
				"source_doctype": source_doctype,
				"company": gate_scope_company,
				"warehouse": gate_scope_warehouse,
				"supplier_type": None,
			},
		},
		"direct_pr": {
			"flow_name": direct_flow_name,
			"transition_key": direct_transition_key,
			"transition_name": f"FLOW-{direct_flow_name}-TRANS-{direct_transition_key}",
			"binding_name": f"FLOW-{direct_flow_name}-BIND-{_binding_key_for_action(action_key)}",
			"source_node_name": f"FLOW-{direct_flow_name}-NODE-scan",
			"target_node_name": f"FLOW-{direct_flow_name}-NODE-handled",
			"scope_key": "direct-pr-scope",
			"context": {
				"source_doctype": source_doctype,
				"company": gate_scope_company,
				"warehouse": direct_scope_warehouse,
				"supplier_type": None,
			},
		},
	}


def ensure_scoped_test_warehouses(*, company: str) -> dict[str, str]:
	"""Create deterministic warehouses for scoped integration routing tests."""
	return {
		"gate": _ensure_warehouse_for_company(SCOPED_GATE_WAREHOUSE_NAME, company),
		"direct": _ensure_warehouse_for_company(SCOPED_DIRECT_WAREHOUSE_NAME, company),
	}


def cleanup_dispatch_flow_fixtures(*, flow_name_prefix: str = "IT-Dispatch-Flow") -> None:
	"""Remove fixture flow definitions created by ``ensure_dispatch_flow_fixtures``."""
	flow_names = frappe.get_all(
		"Barcode Flow Definition",
		filters={"flow_name": ["like", f"{flow_name_prefix}::%"]},
		pluck="name",
	)
	_delete_flow_definitions(flow_names)


def cleanup_all_dispatch_flow_fixtures() -> None:
	"""Remove all fixture flows under the ``IT-Dispatch-Flow`` namespace."""
	flow_names = frappe.get_all(
		"Barcode Flow Definition",
		filters={"flow_name": ["like", "IT-Dispatch-Flow%"]},
		pluck="name",
	)
	_delete_flow_definitions(flow_names)


def _delete_flow_definitions(flow_names: list[str]) -> None:
	if not flow_names:
		return

	for doctype in (
		"Barcode Flow Transition",
		"Barcode Flow Action Binding",
		"Barcode Flow Field Map",
		"Barcode Flow Condition",
		"Barcode Flow Node",
	):
		for docname in frappe.get_all(doctype, filters={"flow": ["in", flow_names]}, pluck="name"):
			frappe.delete_doc(doctype, docname, force=True, ignore_permissions=True)

	for flow_name in flow_names:
		frappe.delete_doc("Barcode Flow Definition", flow_name, force=True, ignore_permissions=True)


def cleanup_conflicting_scoped_flow_fixtures() -> None:
	"""Remove scoped-routing fixture flows that can leak across test modules."""
	for prefix in ("IT-Dispatch-Flow-ScopedRoutingIntegration", "IT-Dispatch-Flow-Scoped"):
		cleanup_dispatch_flow_fixtures(flow_name_prefix=prefix)


def _upsert_flow_definition(*, flow_name: str, source_doctype: str, action_rows: list[dict]):
	if frappe.db.exists("Barcode Flow Definition", flow_name):
		flow = frappe.get_doc("Barcode Flow Definition", flow_name)
	else:
		flow = frappe.get_doc({"doctype": "Barcode Flow Definition", "flow_name": flow_name})

	flow.flow_name = flow_name
	flow.is_active = 1
	flow.description = "Integration fixture for dispatch flow resolution"
	flow.set(
		"scopes",
		[
			{
				"doctype": "Barcode Flow Scope",
				"scope_key": "default",
				"priority": 0,
				"is_default": 1,
				"source_doctype": source_doctype,
				"company": None,
				"warehouse": None,
				"supplier_type": None,
				"source_name_field": None,
				"description": None,
			}
		],
	)
	flow.set("nodes", [])
	flow.set("conditions", [])
	flow.set("field_maps", [])
	flow.set("action_bindings", [])
	flow.set("transitions", [])

	if flow.is_new():
		flow.insert(ignore_permissions=True)
	else:
		flow.save(ignore_permissions=True)

	# Explicitly clear optional scope filters to keep fixture matching broad and deterministic.
	for scope in flow.scopes or []:
		frappe.db.set_value(
			"Barcode Flow Scope",
			scope.name,
			{
				"company": "",
				"warehouse": "",
				"supplier_type": "",
				"source_name_field": "",
				"description": "",
			},
			update_modified=False,
		)

	nodes = {
		"scan": _upsert_node(flow=flow.name, node_key="scan", label="Scan", node_type="Start"),
		"handled": _upsert_node(flow=flow.name, node_key="handled", label="Handled", node_type="End"),
	}
	bindings = {}
	transitions = {}
	for row in action_rows:
		action_definition = _get_action_definition(row["action_key"])
		binding = _upsert_action_binding(
			flow=flow.name,
			binding_key=_binding_key_for_action(row["action_key"]),
			action=action_definition["name"],
			custom_handler=row["handler_method"],
		)
		transition = _upsert_transition(
			flow=flow.name,
			transition_key=_transition_key_for_action(row["action_key"]),
			source_node=nodes["scan"].name,
			target_node=nodes["handled"].name,
			action=action_definition["name"],
			action_binding=binding.name,
			priority=100,
		)
		bindings[row["action_key"]] = binding
		transitions[row["action_key"]] = transition

	return {
		"definition": flow,
		"nodes": nodes,
		"bindings": bindings,
		"transitions": transitions,
	}


def _binding_key_for_action(action_key: str) -> str:
	return f"binding-{action_key}"


def _transition_key_for_action(action_key: str) -> str:
	return f"transition-{action_key}"


def _ensure_warehouse_for_company(warehouse_name: str, company: str) -> str:
	existing = frappe.db.get_value(
		"Warehouse",
		{"warehouse_name": warehouse_name, "company": company},
		"name",
	)
	if existing:
		return existing

	warehouse = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": warehouse_name,
			"company": company,
		}
	)
	warehouse.insert(ignore_permissions=True)
	return warehouse.name


def _upsert_scoped_single_action_flow_definition(
	*,
	flow_name: str,
	source_doctype: str,
	action_key: str,
	handler_method: str,
	scope_key: str,
	scope_company: str | None,
	scope_warehouse: str | None,
	scope_supplier_type: str | None,
	transition_key: str,
	scope_priority: int,
):
	if frappe.db.exists("Barcode Flow Definition", flow_name):
		flow = frappe.get_doc("Barcode Flow Definition", flow_name)
	else:
		flow = frappe.get_doc({"doctype": "Barcode Flow Definition", "flow_name": flow_name})

	flow.flow_name = flow_name
	flow.is_active = 1
	flow.description = "Integration fixture for scoped route selection"
	flow.set(
		"scopes",
		[
			{
				"doctype": "Barcode Flow Scope",
				"scope_key": scope_key,
				"priority": scope_priority,
				"is_default": 1,
				"source_doctype": source_doctype,
				"company": scope_company,
				"warehouse": scope_warehouse,
				"supplier_type": scope_supplier_type,
				"source_name_field": None,
				"description": "Integration scoped route fixture",
			}
		],
	)
	flow.set("nodes", [])
	flow.set("conditions", [])
	flow.set("field_maps", [])
	flow.set("action_bindings", [])
	flow.set("transitions", [])

	if flow.is_new():
		flow.insert(ignore_permissions=True)
	else:
		flow.save(ignore_permissions=True)

	nodes = {
		"scan": _upsert_node(flow=flow.name, node_key="scan", label="Scan", node_type="Start"),
		"handled": _upsert_node(flow=flow.name, node_key="handled", label="Handled", node_type="End"),
	}
	action_definition = _get_action_definition(action_key)
	binding = _upsert_action_binding(
		flow=flow.name,
		binding_key=_binding_key_for_action(action_key),
		action=action_definition["name"],
		custom_handler=handler_method,
	)
	_upsert_transition(
		flow=flow.name,
		transition_key=transition_key,
		source_node=nodes["scan"].name,
		target_node=nodes["handled"].name,
		action=action_definition["name"],
		action_binding=binding.name,
		priority=200,
	)

	return flow


def _get_action_definition(action_key: str) -> dict:
	row = frappe.db.get_value(
		"QR Action Definition",
		{"action_key": action_key, "is_active": 1},
		["name", "action_key", "handler_method", "source_doctype"],
		as_dict=True,
	)
	if not row:
		raise frappe.ValidationError(f"Missing active QR Action Definition for {action_key}")
	return row


def _upsert_node(*, flow: str, node_key: str, label: str, node_type: str):
	name = f"FLOW-{flow}-NODE-{node_key}"
	if frappe.db.exists("Barcode Flow Node", name):
		doc = frappe.get_doc("Barcode Flow Node", name)
	else:
		doc = frappe.get_doc({"doctype": "Barcode Flow Node", "flow": flow, "node_key": node_key})

	doc.flow = flow
	doc.node_key = node_key
	doc.label = label
	doc.node_type = node_type
	_save_doc(doc)
	return doc


def _upsert_action_binding(*, flow: str, binding_key: str, action: str, custom_handler: str):
	name = f"FLOW-{flow}-BIND-{binding_key}"
	if frappe.db.exists("Barcode Flow Action Binding", name):
		doc = frappe.get_doc("Barcode Flow Action Binding", name)
	else:
		doc = frappe.get_doc(
			{"doctype": "Barcode Flow Action Binding", "flow": flow, "binding_key": binding_key}
		)

	doc.flow = flow
	doc.binding_key = binding_key
	doc.enabled = 1
	doc.trigger_event = "custom_handler"
	doc.action = action
	doc.custom_handler = custom_handler
	doc.handler_override_wins = 0
	doc.target_node = ""
	doc.target_transition = ""
	_save_doc(doc)
	return doc


def _upsert_transition(
	*,
	flow: str,
	transition_key: str,
	source_node: str,
	target_node: str,
	action: str,
	action_binding: str,
	priority: int,
):
	name = f"FLOW-{flow}-TRANS-{transition_key}"
	if frappe.db.exists("Barcode Flow Transition", name):
		doc = frappe.get_doc("Barcode Flow Transition", name)
	else:
		doc = frappe.get_doc(
			{"doctype": "Barcode Flow Transition", "flow": flow, "transition_key": transition_key}
		)

	doc.flow = flow
	doc.transition_key = transition_key
	doc.enabled = 1
	doc.generation_mode = "runtime"
	doc.source_node = source_node
	doc.target_node = target_node
	doc.action = action
	doc.binding_mode = "custom_handler"
	doc.action_binding = action_binding
	doc.priority = priority
	doc.condition = ""
	doc.field_map = ""
	doc.target_doctype = ""
	_save_doc(doc)
	return doc


def _save_doc(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


@contextmanager
def relational_source_node_resolution() -> Generator[None, None, None]:
	"""Resolve the deterministic start node for integration docs from the active relational flow."""
	from asn_module.qr_engine import dispatch as dispatch_module

	original = dispatch_module._resolve_source_node

	def _resolve(source_doc):
		resolved = original(source_doc)
		if resolved:
			return resolved

		context = dispatch_module._build_flow_resolution_context(source_doc)
		resolved_flow = resolve_flow_with_scope(context)
		flow_definition = resolved_flow[0] if resolved_flow else None
		if not flow_definition:
			return None

		return f"FLOW-{flow_definition.name}-NODE-scan"

	with patch("asn_module.qr_engine.dispatch._resolve_source_node", side_effect=_resolve):
		yield


@contextmanager
def integration_user_context(email: str = INTEGRATION_USER_EMAIL) -> Generator[None, None, None]:
	"""Run code as ``email``, restoring the previous session user afterward."""
	previous = frappe.session.user
	frappe.set_user(email)
	try:
		yield
	finally:
		frappe.set_user(previous)
