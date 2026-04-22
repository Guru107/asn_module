import time
from contextlib import contextmanager

import frappe

DEFAULT_QR_ACTION_DEFINITIONS = [
	{
		"action_key": "create_purchase_receipt",
		"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
		"source_doctype": "ASN",
		"roles": ["Stock User", "Stock Manager"],
	},
	{
		"action_key": "create_stock_transfer",
		"handler_method": "asn_module.handlers.stock_transfer.create_from_quality_inspection",
		"source_doctype": "Quality Inspection",
		"roles": ["Stock User", "Stock Manager"],
	},
	{
		"action_key": "create_purchase_return",
		"handler_method": "asn_module.handlers.purchase_return.create_from_quality_inspection",
		"source_doctype": "Quality Inspection",
		"roles": ["Stock User", "Stock Manager"],
	},
	{
		"action_key": "create_purchase_invoice",
		"handler_method": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
		"source_doctype": "Purchase Receipt",
		"roles": ["Accounts User", "Accounts Manager"],
	},
	{
		"action_key": "confirm_putaway",
		"handler_method": "asn_module.handlers.putaway.confirm_putaway",
		"source_doctype": "Purchase Receipt",
		"roles": ["Stock User", "Stock Manager"],
	},
	{
		"action_key": "create_subcontracting_dispatch",
		"handler_method": "asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order",
		"source_doctype": "Subcontracting Order",
		"roles": ["Stock User", "Stock Manager"],
	},
	{
		"action_key": "create_subcontracting_receipt",
		"handler_method": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
		"source_doctype": "Subcontracting Order",
		"roles": ["Stock User", "Stock Manager"],
	},
]


@contextmanager
def _named_lock(lock_name: str, *, timeout: int = 30, failure_message: str):
	lock_acquired = frappe.db.sql("SELECT GET_LOCK(%s, %s)", (lock_name, timeout))[0][0]
	if not lock_acquired:
		raise frappe.ValidationError(failure_message)

	try:
		yield
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))


def sync_qr_action_definitions():
	"""Seed the persisted QR action catalog with the app's default definitions."""
	with _named_lock(
		"asn_module:qr_action_definition:sync",
		failure_message="Failed to acquire lock for QR action definition sync",
	):
		existing_action_keys = set(
			frappe.get_all(
				"QR Action Definition",
				filters={"action_key": ["in", [row["action_key"] for row in DEFAULT_QR_ACTION_DEFINITIONS]]},
				pluck="action_key",
			)
		)
		for row in DEFAULT_QR_ACTION_DEFINITIONS:
			if row["action_key"] in existing_action_keys:
				continue

			frappe.get_doc(
				{
					"doctype": "QR Action Definition",
					"action_key": row["action_key"],
					"handler_method": row["handler_method"],
					"source_doctype": row["source_doctype"],
					"allowed_roles": ",".join(row["roles"]),
					"is_active": 1,
				}
			).insert(ignore_permissions=True, ignore_if_duplicate=True)
			existing_action_keys.add(row["action_key"])


def get_canonical_actions() -> list[dict]:
	"""Active QR actions from the persisted source-of-truth catalog."""
	sync_qr_action_definitions()
	actions = frappe.get_all(
		"QR Action Definition",
		filters={"is_active": 1},
		fields=["action_key", "handler_method", "source_doctype", "allowed_roles"],
		order_by="action_key asc",
	)
	return [
		{
			"action_key": row.action_key,
			"handler_method": row.handler_method,
			"source_doctype": row.source_doctype,
			"roles": [role.strip() for role in (row.allowed_roles or "").split(",") if role.strip()],
		}
		for row in actions
	]


def register_actions():
	"""Project active QR action definitions into the QR Action Registry singleton."""
	sync_qr_action_definitions()
	actions = frappe.get_all(
		"QR Action Definition",
		filters={"is_active": 1},
		fields=["action_key", "handler_method", "source_doctype", "allowed_roles"],
		order_by="action_key asc",
	)
	last_error = None
	with _named_lock(
		"asn_module:qr_action_registry:register_actions",
		failure_message="Failed to acquire lock for QR action registry update",
	):
		for attempt in range(3):
			save_point = f"register_actions_retry_{attempt}"
			frappe.db.savepoint(save_point)
			registry = frappe.get_single("QR Action Registry")
			registry.actions = []

			for row in actions:
				registry.append(
					"actions",
					{
						"action_key": row.action_key,
						"handler_method": row.handler_method,
						"source_doctype": row.source_doctype,
						"allowed_roles": row.allowed_roles,
					},
				)

			try:
				registry.save(ignore_permissions=True)
				return
			except (frappe.TimestampMismatchError, frappe.QueryDeadlockError) as err:
				last_error = err
				frappe.db.rollback(save_point=save_point)
				time.sleep(0.02 * (attempt + 1))
				continue
		if last_error:
			raise last_error
