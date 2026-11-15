"""Utilities invoked via ``bench --site SITE execute asn_module.commands.<function>``."""

import frappe
from frappe import _
from pypika.terms import ExistsCriterion

from asn_module.setup_actions import ACTIONS


def _orphan_scan_code_rows() -> list:
	"""NOT EXISTS anti-join against each registry source doctype's table.

	Source doctypes come from the code-defined action registry. A row pointing at
	any other (or no) doctype can only be DB drift, so it is reported as an orphan.
	Registry doctypes whose app is not installed (e.g. Gate Pass) are skipped:
	MySQL validates every referenced table at prepare time, so one unconditional
	query would crash on sites without them. Two constant round trips (doctype
	filter + anti-join), independent of registry size.
	"""
	registry_doctypes = sorted({action["source_doctype"] for action in ACTIONS.values()})
	installed = set(frappe.get_all("DocType", filters={"name": ("in", registry_doctypes)}, pluck="name"))
	sc = frappe.qb.DocType("Scan Code")
	source_exists = None
	for doctype in registry_doctypes:
		if doctype not in installed:
			continue
		src = frappe.qb.DocType(doctype)
		branch = (sc.source_doctype == doctype) & ExistsCriterion(
			frappe.qb.from_(src).select(1).where(src.name == sc.source_name)
		)
		source_exists = branch if source_exists is None else source_exists | branch
	if source_exists is None:
		return frappe.get_all("Scan Code", fields=["name", "scan_code", "source_doctype", "source_name"])
	return (
		frappe.qb.from_(sc)
		.select(sc.name, sc.scan_code, sc.source_doctype, sc.source_name)
		.where(source_exists.negate())
	).run(as_dict=True)


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
