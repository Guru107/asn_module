import json

import frappe
from frappe import _

from asn_module.traceability import emit_asn_item_transition


def confirm_putaway(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Log a putaway confirmation scan. No stock movement — audit only.

	Args:
		source_doctype: Source document type (e.g. Purchase Receipt).
		source_name: Source document name.
		payload: Full token payload (unused for logging; kept for handler signature consistency).

	Returns:
		dict with doctype, name, url, message
	"""
	del payload

	if not frappe.db.exists("DocType", source_doctype):
		frappe.throw(_("Invalid source document type: {0}").format(source_doctype))
	if not frappe.db.exists(source_doctype, source_name):
		frappe.throw(_("Source document not found: {0} {1}").format(source_doctype, source_name))

	if source_doctype == "Purchase Receipt":
		pr = frappe.get_doc("Purchase Receipt", source_name)
		if pr.asn:
			asn_items_map = json.loads(pr.asn_items or "{}")
			for pr_item in pr.items:
				mapping = asn_items_map.get(str(pr_item.idx))
				if not mapping:
					continue
				emit_asn_item_transition(
					asn=pr.asn,
					asn_item=mapping.get("asn_item_name"),
					item_code=pr_item.item_code,
					state="PUTAWAY_CONFIRMED",
					transition_status="OK",
					ref_doctype="Purchase Receipt",
					ref_name=pr.name,
				)

	log = frappe.get_doc(
		{
			"doctype": "Scan Log",
			"action": "confirm_putaway",
			"source_doctype": source_doctype,
			"source_name": source_name,
			"result": "Success",
			"device_info": "Desktop",
		}
	).insert(ignore_permissions=True)

	return {
		"doctype": "Scan Log",
		"name": log.name,
		"url": f"/app/scan-log/{log.name}",
		"message": _("Putaway confirmed for {0} {1}").format(source_doctype, source_name),
	}
