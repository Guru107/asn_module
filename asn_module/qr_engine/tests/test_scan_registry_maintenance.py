import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from asn_module.asn_module.doctype.scan_log.scan_log import LOG_RETENTION_DAYS, ScanLog


def _index_column_orders(table: str) -> list[list[str]]:
	"""Return {index_name: [columns in position order]} values for a table."""
	rows = frappe.db.sql(
		"""
		SELECT INDEX_NAME, COLUMN_NAME
		FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
		ORDER BY INDEX_NAME, SEQ_IN_INDEX
		""",
		(f"tab{table}",),
	)
	indexes: dict[str, list[str]] = {}
	for name, column in rows:
		indexes.setdefault(name, []).append(column)
	return list(indexes.values())


def _assert_index_leading_columns(test_case, table: str, columns: tuple[str, ...]) -> None:
	indexes = _index_column_orders(table)
	test_case.assertTrue(
		any(cols[: len(columns)] == list(columns) for cols in indexes),
		f"{table} has no index leading with {columns}; indexes: {indexes}",
	)


class TestScanRegistryIndexes(FrappeTestCase):
	"""The on-trash hook filters must be served by index-leading columns."""

	def test_scan_code_source_index(self):
		_assert_index_leading_columns(self, "Scan Code", ("source_doctype", "source_name"))

	def test_scan_log_result_index(self):
		_assert_index_leading_columns(self, "Scan Log", ("result_doctype", "result_name"))

	def test_scan_log_source_index(self):
		_assert_index_leading_columns(self, "Scan Log", ("source_doctype", "source_name"))


class TestScanLogClearing(FrappeTestCase):
	def test_clear_old_logs_deletes_only_expired_rows(self):
		old_log = frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "_test_retention",
				"source_doctype": "DocType",
				"source_name": "DocType",
				"result": "Success",
			}
		).insert(ignore_permissions=True)
		recent_log = frappe.get_doc(
			{
				"doctype": "Scan Log",
				"action": "_test_retention",
				"source_doctype": "DocType",
				"source_name": "DocType",
				"result": "Success",
			}
		).insert(ignore_permissions=True)
		old_creation = add_to_date(now_datetime(), days=-(LOG_RETENTION_DAYS + 1))
		frappe.db.sql(
			"UPDATE `tabScan Log` SET creation = %s WHERE name = %s",
			(old_creation, old_log.name),
		)

		ScanLog.clear_old_logs(LOG_RETENTION_DAYS)

		self.assertFalse(frappe.db.exists("Scan Log", old_log.name))
		self.assertTrue(frappe.db.exists("Scan Log", recent_log.name))

		frappe.db.delete("Scan Log", {"action": "_test_retention"})
