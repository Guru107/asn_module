import frappe


def ensure_quality_inspection_purchase_receipt_item_column() -> None:
	"""Ensure ``Quality Inspection.purchase_receipt_item`` exists for cross-version tests.

	Frappe/ERPNext test sites can vary by framework patch level, and this test path
	reads/writes ``purchase_receipt_item`` explicitly. Keep this guard centralized so
	the rationale and behavior are consistent across suites.
	"""
	if frappe.db.has_column("Quality Inspection", "purchase_receipt_item"):
		return
	frappe.db.commit()
	frappe.db.sql(
		"ALTER TABLE `tabQuality Inspection` ADD COLUMN `purchase_receipt_item` VARCHAR(255)",
		ignore_ddl=True,
	)
