import frappe

_REGISTRY_DOCTYPES = ("QR Action Registry", "QR Action Registry Item")
_DOCTYPE_CHILD_TABLES = (
	"DocField",
	"DocPerm",
	"DocType Action",
	"DocType Link",
	"DocType State",
)


def execute():
	"""Drop the DB action registry and the unused Scan Code expiry column.

	Action rows were a copy of ``setup_actions.ACTIONS``.
	"""
	_clear_scan_code_lifecycle()
	for name in _REGISTRY_DOCTYPES:
		_drop_doctype(name)
	frappe.clear_cache()


def _clear_scan_code_lifecycle() -> None:
	if not frappe.db.table_exists("Scan Code"):
		return
	if frappe.db.has_column("Scan Code", "expires_on"):
		frappe.db.sql_ddl("ALTER TABLE `tabScan Code` DROP COLUMN `expires_on`")


def _drop_doctype(name: str) -> None:
	if frappe.db.exists("DocType", name):
		for child in _DOCTYPE_CHILD_TABLES:
			if frappe.db.table_exists(child):
				frappe.db.delete(child, {"parent": name})
		if frappe.db.table_exists("Singles"):
			frappe.db.delete("Singles", {"doctype": name})
		frappe.db.delete("DocType", {"name": name})
	# sql_ddl commits first, so a re-run with nothing to drop must not reach it.
	if frappe.db.table_exists(name, cached=False):
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{name}`")
	frappe.clear_cache(doctype=name)
