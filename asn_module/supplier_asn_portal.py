"""Supplier portal rules for ASN (cancel eligibility, purchase receipt checks)."""

from __future__ import annotations

import frappe


def purchase_receipt_exists_for_asn(asn_name: str) -> bool:
	"""True if any non-cancelled Purchase Receipt references this ASN."""
	if not asn_name:
		return False
	return bool(
		frappe.db.exists("Purchase Receipt", {"asn": asn_name, "docstatus": ("!=", 2)})
	)


def asn_eligible_for_supplier_portal_cancel(doc) -> bool:
	"""
	Cancel from portal only for submitted ASN in Submitted status, with no active PR.
	Partially/fully received ASNs imply receipt activity and are excluded by status.
	"""
	return (
		doc.docstatus == 1
		and getattr(doc, "status", None) == "Submitted"
		and not purchase_receipt_exists_for_asn(doc.name)
	)
