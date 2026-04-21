"""Reusable ASN → draft PR → submit PR → draft PI via ``dispatch`` (integration paths)."""

from __future__ import annotations

from types import SimpleNamespace

import frappe

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
	real_asn_attachment_context,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.tests.integration.fixtures import (
	cleanup_conflicting_scoped_flow_fixtures,
	integration_user_context,
)


def run_asn_pr_pi_via_dispatch(*, supplier_invoice_no: str, qty: float = 10) -> SimpleNamespace:
	"""Full happy path under ``integration_user_context`` with real ASN attachments and no PR submit mocks."""
	cleanup_conflicting_scoped_flow_fixtures()
	with integration_user_context():
		purchase_order = create_purchase_order(qty=qty)
		asn = make_test_asn(
			purchase_order=purchase_order,
			supplier_invoice_no=supplier_invoice_no,
			qty=qty,
		)
		asn.insert(ignore_permissions=True)
		with real_asn_attachment_context():
			asn.submit()
		asn.reload()

		pr_code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		pr_result = dispatch(code=pr_code, device_info="integration")
		if not pr_result.get("success"):
			raise AssertionError(f"dispatch PR failed: {pr_result}")
		pr = frappe.get_doc("Purchase Receipt", pr_result["name"])
		warehouse = purchase_order.items[0].warehouse
		for row in pr.items:
			row.warehouse = warehouse
		pr.save(ignore_permissions=True)
		pr.submit()

		asn.reload()

		pi_code = get_or_create_scan_code("create_purchase_invoice", "Purchase Receipt", pr.name)
		pi_result = dispatch(code=pi_code, device_info="integration")
		if not pi_result.get("success"):
			raise AssertionError(f"dispatch PI failed: {pi_result}")
		pi = frappe.get_doc("Purchase Invoice", pi_result["name"])

		return SimpleNamespace(
			asn=asn,
			purchase_order=purchase_order,
			pr=pr,
			pi=pi,
			pr_code=pr_code,
			pi_code=pi_code,
		)


def run_asn_pr_submitted_via_dispatch(*, supplier_invoice_no: str, qty: float = 10) -> SimpleNamespace:
	"""ASN submitted → draft PR via dispatch → PR submitted (no PI)."""
	cleanup_conflicting_scoped_flow_fixtures()
	with integration_user_context():
		purchase_order = create_purchase_order(qty=qty)
		asn = make_test_asn(
			purchase_order=purchase_order,
			supplier_invoice_no=supplier_invoice_no,
			qty=qty,
		)
		asn.insert(ignore_permissions=True)
		with real_asn_attachment_context():
			asn.submit()
		asn.reload()

		pr_code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		pr_result = dispatch(code=pr_code, device_info="integration")
		if not pr_result.get("success"):
			raise AssertionError(f"dispatch PR failed: {pr_result}")
		pr = frappe.get_doc("Purchase Receipt", pr_result["name"])
		warehouse = purchase_order.items[0].warehouse
		for row in pr.items:
			row.warehouse = warehouse
		pr.save(ignore_permissions=True)
		pr.submit()

		asn.reload()
		return SimpleNamespace(asn=asn, purchase_order=purchase_order, pr=pr, pr_code=pr_code)
