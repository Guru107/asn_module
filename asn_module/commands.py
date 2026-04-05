"""Utilities invoked via ``bench --site SITE execute asn_module.commands.<function>``."""

import frappe
from frappe import _

from asn_module.qr_engine.scan_codes import verify_registry_row_points_to_existing_source
from asn_module.setup_actions import get_canonical_actions


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


def verify_qr_action_registry():
	"""Report drift between current QR Action Registry and canonical app-managed actions."""
	registry = frappe.get_single("QR Action Registry")
	current_rows = {}
	for row in registry.actions or []:
		current_rows[row.action_key] = {
			"handler_method": row.handler_method,
			"source_doctype": row.source_doctype,
			"allowed_roles": sorted([role.strip() for role in (row.allowed_roles or "").split(",") if role.strip()]),
		}

	canonical_rows = {}
	for row in get_canonical_actions():
		canonical_rows[row["action_key"]] = {
			"handler_method": row["handler_method"],
			"source_doctype": row["source_doctype"],
			"allowed_roles": sorted(row["roles"]),
		}

	missing = sorted(set(canonical_rows) - set(current_rows))
	unexpected = sorted(set(current_rows) - set(canonical_rows))
	mismatched = []
	for action_key in sorted(set(canonical_rows).intersection(current_rows)):
		expected = canonical_rows[action_key]
		actual = current_rows[action_key]
		diffs = {}
		for field in ("handler_method", "source_doctype", "allowed_roles"):
			if expected[field] == actual[field]:
				continue
			diffs[field] = {"expected": expected[field], "actual": actual[field]}
		if diffs:
			mismatched.append({"action_key": action_key, "diffs": diffs})

	ok = not missing and not unexpected and not mismatched
	if ok:
		frappe.msgprint(_("QR Action Registry matches canonical actions."))
		return {
			"ok": True,
			"missing": [],
			"unexpected": [],
			"mismatched": [],
		}

	frappe.msgprint(
		_(
			"QR Action Registry drift detected. missing={0}, unexpected={1}, mismatched={2}"
		).format(len(missing), len(unexpected), len(mismatched)),
		title=_("QR Action Registry check"),
		indicator="orange",
	)
	return {
		"ok": False,
		"missing": missing,
		"unexpected": unexpected,
		"mismatched": mismatched,
	}
