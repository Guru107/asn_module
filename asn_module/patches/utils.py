import frappe

_DOCTYPE_CHILD_TABLES = (
	"DocField",
	"DocPerm",
	"DocType Action",
	"DocType Link",
	"DocType State",
)


def drop_doctype(name: str) -> None:
	"""Remove a retired DocType's metadata and its table; safe to re-run.

	``frappe.delete_doc("DocType", ...)`` leaves the table behind, so it is dropped here.
	"""
	if frappe.db.exists("DocType", name):
		for child in _DOCTYPE_CHILD_TABLES:
			if frappe.db.table_exists(child):
				frappe.db.delete(child, {"parent": name})
		if frappe.db.table_exists("Singles"):
			frappe.db.delete("Singles", {"doctype": name})
		frappe.db.delete("DocType", {"name": name})
	# sql_ddl commits first, so a re-run with nothing to drop must not reach it.
	if frappe.db.table_exists(name, cached=False):
		# A table name cannot be a bound parameter; callers pass fixed DocType names, never input.
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{name}`")
	frappe.clear_cache(doctype=name)
