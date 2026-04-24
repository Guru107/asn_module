from __future__ import annotations

import frappe

from asn_module.barcode_process_flow import runtime


def on_any_submit(doc, method):
	"""Generate follow-up scan codes for submit-time conditioned steps."""
	del method

	try:
		runtime.generate_codes_for_source_doc(source_doc=doc, conditioned_only=True)
	except Exception:
		frappe.log_error(
			title="Barcode Process Flow submit barcode generation failed",
			message=frappe.get_traceback(),
		)
