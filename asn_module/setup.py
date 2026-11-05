import frappe

from asn_module.asn_module.doctype.scan_log.scan_log import LOG_RETENTION_DAYS
from asn_module.custom_fields.gate_pass import setup as setup_gate_pass_fields
from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.custom_fields.subcontracting_receipt import setup as setup_scr_fields
from asn_module.notifications.setup import create_notifications


def register_scan_log_clearing() -> None:
	"""Register Scan Log in Log Settings for automatic clearing; idempotent.

	``register_doctype`` appends the row when missing and updates the retention
	when present, so repeat calls keep exactly one row.
	"""
	if not frappe.db.exists("DocType", "Scan Log"):
		return
	log_settings = frappe.get_doc("Log Settings")
	log_settings.register_doctype("Scan Log", LOG_RETENTION_DAYS)
	log_settings.save()


def after_install():
	setup_pr_fields()
	setup_gate_pass_fields()
	setup_scr_fields()
	setup_pi_fields()
	create_notifications()
	register_scan_log_clearing()


def after_migrate():
	setup_pr_fields()
	setup_gate_pass_fields()
	setup_scr_fields()
	setup_pi_fields()
	# Idempotent by name; sites that installed before the templates existed pick them up here.
	create_notifications()
	register_scan_log_clearing()
