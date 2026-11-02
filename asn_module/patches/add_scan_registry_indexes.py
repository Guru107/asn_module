def execute():
	"""Backfill covering indexes for the scan-registry delete-hook lookups.

	New sites get them from ``on_doctype_update`` during doctype sync; patches are
	marked completed without running on fresh installs, so this exists for sites
	installed before this change. Both calls are idempotent
	(``ADD INDEX IF NOT EXISTS``).
	"""
	from asn_module.asn_module.doctype.scan_code import scan_code
	from asn_module.asn_module.doctype.scan_log import scan_log

	scan_code.on_doctype_update()
	scan_log.on_doctype_update()
