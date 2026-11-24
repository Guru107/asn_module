import frappe

from asn_module.patches.utils import drop_doctype

_REGISTRY_DOCTYPES = ("QR Action Registry", "QR Action Registry Item")


def execute():
	"""Drop the DB action registry and the unused Scan Code expiry column.

	Action rows were a copy of ``setup_actions.ACTIONS``.
	"""
	_clear_scan_code_lifecycle()
	for name in _REGISTRY_DOCTYPES:
		drop_doctype(name)
	frappe.clear_cache()


def _clear_scan_code_lifecycle() -> None:
	if not frappe.db.table_exists("Scan Code"):
		return
	if frappe.db.has_column("Scan Code", "expires_on"):
		frappe.db.sql_ddl("ALTER TABLE `tabScan Code` DROP COLUMN `expires_on`")
