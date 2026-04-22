from __future__ import annotations

from typing import Any

from asn_module.barcode_process_flow import capabilities


def get_standard_handler_templates(*, from_doctype: str | None = None) -> list[dict[str, Any]]:
	"""Return runtime-supported built-in handler templates for the current ERP version."""
	return capabilities.get_supported_templates(from_doctype=from_doctype)


def get_canonical_actions() -> list[dict[str, Any]]:
	"""Compatibility helper retained for bench commands/tests.

	In the hard-cut model there is no QR Action Registry; this returns capability-backed
	handler descriptors for observability tooling.
	"""
	rows = []
	for template in get_standard_handler_templates():
		rows.append(
			{
				"action_key": template["key"],
				"handler_method": template["handler"],
				"source_doctype": template["from_doctype"],
				"roles": [],
			}
		)
	return rows


def sync_qr_action_definitions():
	"""Legacy no-op retained to keep existing install hooks import-safe."""
	return None


def register_actions():
	"""Legacy no-op retained to keep existing install hooks import-safe."""
	return None
