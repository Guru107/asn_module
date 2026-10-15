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
