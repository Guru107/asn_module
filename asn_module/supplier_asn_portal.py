"""Supplier portal rules for ASN (cancel eligibility, purchase receipt checks)."""

from __future__ import annotations

import frappe


def purchase_receipt_exists_for_asn(asn_name: str) -> bool:
	"""True if any non-cancelled Purchase Receipt references this ASN."""
	if not asn_name:
		return False
	if not frappe.db.has_column("Purchase Receipt", "asn"):
		return False
	return bool(frappe.db.exists("Purchase Receipt", {"asn": asn_name, "docstatus": ("!=", 2)}))


def purchase_receipt_linked_to_asn(asn_name: str) -> bool:
	"""True if any Purchase Receipt row still references this ASN (any docstatus)."""
	if not asn_name:
		return False
	if not frappe.db.has_column("Purchase Receipt", "asn"):
		return False
	return bool(frappe.db.exists("Purchase Receipt", {"asn": asn_name}))


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


def asn_eligible_for_supplier_portal_delete(doc) -> bool:
	"""Supplier may remove a cancelled notice when no draft/submitted receipt still references it.

	Cancelled purchase receipts do not block (same rule as portal cancel).
	"""
	return doc.docstatus == 2 and not purchase_receipt_exists_for_asn(doc.name)
