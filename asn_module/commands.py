"""Utilities invoked via ``bench --site SITE execute asn_module.commands.<function>``."""

import frappe
from frappe import _

from asn_module.qr_engine.scan_codes import verify_registry_row_points_to_existing_source


def verify_scan_code_registry():
	"""Report Scan Code rows whose source document is missing (integrity check).

	Returns ``{"ok": bool, "orphan_count": int, "orphans": [...]}``.
	"""
	if not frappe.has_permission("Scan Code", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	orphans = []
	for row in frappe.get_all(
		"Scan Code",
		fields=["name", "scan_code", "source_doctype", "source_name"],
	):
		doc = frappe.get_doc("Scan Code", row.name)
		if verify_registry_row_points_to_existing_source(doc):
			continue
		orphans.append(row)

	if not orphans:
		frappe.msgprint(_("All scan codes point to existing source documents."))
		return {"ok": True, "orphan_count": 0, "orphans": []}

	frappe.msgprint(
		_("{0} orphan scan code(s) found.").format(len(orphans)),
		title=_("Scan Code registry check"),
		indicator="orange",
	)
	return {"ok": False, "orphan_count": len(orphans), "orphans": orphans}


def verify_barcode_process_flow():
	"""Quick health-check for one-screen Barcode Process Flow configuration."""
	if not frappe.db.exists("DocType", "Barcode Process Flow"):
		message = _("DocType Barcode Process Flow is not installed on this site yet. Run bench migrate.")
		frappe.msgprint(message, indicator="orange")
		return {"ok": False, "active_flows": 0, "active_steps": 0, "message": message}

	if not frappe.has_permission("Barcode Process Flow", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	active_flow_names = frappe.get_all(
		"Barcode Process Flow",
		filters={"is_active": 1},
		pluck="name",
	)
	if not active_flow_names:
		frappe.msgprint(_("No active Barcode Process Flow records found."), indicator="orange")
		return {"ok": False, "active_flows": 0, "active_steps": 0}

	active_steps = 0
	for flow_name in active_flow_names:
		flow = frappe.get_doc("Barcode Process Flow", flow_name)
		active_steps += sum(1 for step in (flow.steps or []) if int(step.is_active or 0) == 1)

	frappe.msgprint(
		_("Active Barcode Process Flows: {0}; Active Steps: {1}").format(
			len(active_flow_names),
			active_steps,
		),
		indicator="green",
	)
	return {"ok": True, "active_flows": len(active_flow_names), "active_steps": active_steps}


def verify_qr_action_registry():
	"""Legacy compatibility command retained after hard cut."""
	message = _(
		"QR Action Registry is removed in the hard-cut one-screen model. "
		"Use verify_barcode_process_flow instead."
	)
	frappe.msgprint(message, title=_("Deprecated command"), indicator="orange")
	return {"ok": False, "deprecated": True, "message": message}
