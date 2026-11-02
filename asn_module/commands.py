"""Utilities invoked via ``bench --site SITE execute asn_module.commands.<function>``."""

import frappe
from frappe import _

from asn_module.setup_actions import ACTIONS


def _orphan_scan_code_rows() -> list:
	"""One round trip: NOT EXISTS against each registered source doctype's table.

	Source doctypes come from the code-defined action registry. A row pointing at
	any other (or no) doctype can only be DB drift, so it is reported as an orphan.
	"""
	branches = []
	params = []
	for doctype in sorted({action["source_doctype"] for action in ACTIONS.values()}):
		branches.append(
			f"(sc.source_doctype = %s"
			f" AND EXISTS (SELECT 1 FROM `tab{doctype}` src WHERE src.name = sc.source_name))"
		)
		params.append(doctype)
	return frappe.db.sql(
		f"""
		SELECT sc.name, sc.scan_code, sc.source_doctype, sc.source_name
		FROM `tabScan Code` sc
		WHERE NOT ({" OR ".join(branches)})
		""",
		params,
		as_dict=True,
	)


def verify_scan_code_registry():
	"""Report Scan Code rows whose source document is missing (integrity check).

	Returns ``{"ok": bool, "orphan_count": int, "orphans": [...]}``.
	"""
	if not frappe.has_permission("Scan Code", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	orphans = _orphan_scan_code_rows()

	if not orphans:
		frappe.msgprint(_("All scan codes point to existing source documents."))
		return {"ok": True, "orphan_count": 0, "orphans": []}

	frappe.msgprint(
		_("{0} orphan scan code(s) found.").format(len(orphans)),
		title=_("Scan Code registry check"),
		indicator="orange",
	)
	return {"ok": False, "orphan_count": len(orphans), "orphans": orphans}
