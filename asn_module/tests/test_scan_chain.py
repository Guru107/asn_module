"""Scan-driven chains: one scan per arrow from ASN to Purchase Invoice.

Material:  ASN → Gate Pass → Purchase Receipt → Purchase Invoice
Job:       ASN → Gate Pass → Subcontracting Receipt → Purchase Receipt → Purchase Invoice

Every arrow dispatches the code attached to the previous document. Gate Pass
and Subcontracting Receipt reach docstatus 1 the way the rest of this suite
does (``db.set_value``), because their ERPNext submit paths carry stock rules
this module does not own; the submit hooks are exercised directly.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
	real_asn_attachment_context,
)
from asn_module.handlers.purchase_receipt import (
	ASN_GATE_PASS_SCAN_ACTION,
	GATE_PASS_RECEIPT_ACTION,
	on_gate_pass_cancel,
	on_gate_pass_submit,
)
from asn_module.handlers.subcontracting import (
	SUBCONTRACTING_RECEIPT_PR_ACTION,
	create_receipt_from_subcontracting_receipt,
	on_subcontracting_receipt_cancel,
	on_subcontracting_receipt_submit,
)
from asn_module.handlers.tests.test_subcontracting import (
	TestSubcontractingHandlers,
	patch_subcontracting_incoming_rate,
)
from asn_module.handlers.utils import fill_custom_fiscal_year
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import get_action
from asn_module.templates.pages.asn_new_services import create_job_asn_for_supplier
from asn_module.tests.integration.fixtures import (
	block_commits_for_tests,
	ensure_integration_user,
	integration_user_context,
	with_gate_pass_mode,
)
from asn_module.tests.test_job_asn_and_material_gate_pass import ensure_gate_pass_for_tests
from asn_module.utils.test_setup import apply_receipt_site_requirements, before_tests


def _submitted_material_asn(qty=2):
	purchase_order = create_purchase_order(qty=4)
	asn = make_test_asn(
		purchase_order=purchase_order,
		supplier_invoice_no=f"CHAIN-{frappe.generate_hash(length=8)}",
		qty=qty,
	)
	asn.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()
	return purchase_order, asn


def _submitted_job_asn(shipped_qty=1):
	subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
	finished_good = subcontracting_order.items[0]
	asn = create_job_asn_for_supplier(
		supplier=subcontracting_order.supplier,
		subcontracting_order=subcontracting_order.name,
		header={
			"supplier_invoice_no": f"JOB-CHAIN-{frappe.generate_hash(length=8)}",
			"supplier_invoice_date": today(),
			"vehicle_number": "MH12AB1234",
			"supplier_invoice_amount": shipped_qty * finished_good.rate,
		},
		lines=[{"subcontracting_order_item": finished_good.name, "qty": shipped_qty}],
	)
	with real_asn_attachment_context():
		asn.submit()
	return subcontracting_order, asn


def _gate_pass_opened_by_scan(asn):
	code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
	result = dispatch(code=code, device_info="scan-chain")
	if not result.get("success"):
		raise AssertionError(f"dispatch failed: {result}")
	return frappe.get_doc("Gate Pass", result["name"])


def _submit_by_flag(doctype, name):
	frappe.db.set_value(doctype, name, "docstatus", 1, update_modified=False)


from asn_module.qr_engine.scan_codes import format_scan_code_for_display


def _scan_code_attachment_names(code: str) -> tuple[str, str]:
	label = format_scan_code_for_display(code)
	return f"{label}-qr.png", f"{label}-barcode.png"


def _attached_file_names(doctype, name):
	return frappe.get_all(
		"File",
		{"attached_to_doctype": doctype, "attached_to_name": name},
		pluck="file_name",
	)


def _scan_code_for(action, doctype, name):
	return frappe.db.get_value(
		"Scan Code",
		{"action_key": action, "source_doctype": doctype, "source_name": name},
		"name",
	)


class TestScanChainWiring(FrappeTestCase):
	def test_actions_cover_the_gate_pass_and_subcontracting_receipt_steps(self):
		gate_pass = get_action(GATE_PASS_RECEIPT_ACTION)
		self.assertEqual(gate_pass["source_doctype"], "Gate Pass")
		self.assertEqual(gate_pass["allowed_roles"], ["Stock User", "Stock Manager"])

		scr = get_action(SUBCONTRACTING_RECEIPT_PR_ACTION)
		self.assertEqual(scr["source_doctype"], "Subcontracting Receipt")
		self.assertEqual(scr["allowed_roles"], ["Stock User", "Stock Manager"])

	def test_the_scan_code_field_is_read_only_and_not_copied(self):
		before_tests()
		ensure_gate_pass_for_tests()
		for doctype, after in (("Gate Pass", "asn"), ("Purchase Receipt", "asn_items")):
			meta = frappe.get_meta(doctype)
			field = meta.get_field("scan_code")
			self.assertIsNotNone(field, f"{doctype} has the Scan Code field")
			self.assertTrue(field.read_only)
			self.assertTrue(field.no_copy, "a duplicate must not inherit another document's code")
			fieldnames = [df.fieldname for df in meta.fields]
			self.assertEqual(fieldnames.index("scan_code"), fieldnames.index(after) + 1)
		self.assertIsNone(frappe.get_meta("Purchase Invoice").get_field("scan_code"))

	def test_doc_events_wire_the_chain_handlers(self):
		events = frappe.get_hooks("doc_events")
		self.assertIn(
			"asn_module.handlers.purchase_receipt.on_gate_pass_submit",
			events["Gate Pass"]["on_submit"],
		)
		self.assertIn(
			"asn_module.handlers.purchase_receipt.on_gate_pass_cancel",
			events["Gate Pass"]["on_cancel"],
		)
		self.assertIn(
			"asn_module.handlers.subcontracting.on_subcontracting_receipt_submit",
			events["Subcontracting Receipt"]["on_submit"],
		)
		self.assertIn(
			"asn_module.handlers.subcontracting.on_subcontracting_receipt_cancel",
			events["Subcontracting Receipt"]["on_cancel"],
		)


class TestGatePassScanChain(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()
		ensure_gate_pass_for_tests()
		block_commits_for_tests(cls)

	def test_submitting_a_gate_pass_stores_the_receipt_code(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			self.assertFalse(
				frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code"),
				"a draft Gate Pass carries no code",
			)

			on_gate_pass_submit(gate_pass)

		code = _scan_code_for(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)
		self.assertTrue(code)
		self.assertEqual(frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code"), code)
		self.assertEqual(_attached_file_names("Gate Pass", gate_pass.name), [])

	def test_a_doctype_without_the_scan_code_field_submits_without_a_code(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			meta = frappe.get_meta("Gate Pass")
			with patch.object(meta, "has_field", return_value=False):
				on_gate_pass_submit(gate_pass)

		self.assertEqual(frappe.db.count("Scan Code", {"source_name": gate_pass.name}), 0)

	def test_a_gate_pass_without_an_asn_gets_no_code(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			frappe.db.set_value("Gate Pass", gate_pass.name, "asn", "", update_modified=False)

			on_gate_pass_submit(frappe.get_doc("Gate Pass", gate_pass.name))

		self.assertEqual(frappe.db.count("Scan Code", {"source_name": gate_pass.name}), 0)
		self.assertFalse(frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code"))

	def test_a_draft_gate_pass_with_a_scan_code_can_be_deleted(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			code = get_or_create_scan_code(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)
			self.assertTrue(frappe.db.exists("Scan Code", code))

			frappe.delete_doc("Gate Pass", gate_pass.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Gate Pass", gate_pass.name))
		self.assertFalse(frappe.db.exists("Scan Code", code))

	def test_a_cancelled_gate_pass_with_voided_scan_codes_can_be_deleted(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			on_gate_pass_submit(gate_pass)
			code = _scan_code_for(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)
			self.assertTrue(code)

			frappe.db.set_value("Gate Pass", gate_pass.name, "docstatus", 2, update_modified=False)
			on_gate_pass_cancel(gate_pass)
			self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Voided")

			frappe.delete_doc("Gate Pass", gate_pass.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Gate Pass", gate_pass.name))
		self.assertFalse(frappe.db.exists("Scan Code", code))

	def test_the_material_chain_creates_a_purchase_receipt_by_scan(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			_submit_by_flag("Gate Pass", gate_pass.name)
			on_gate_pass_submit(gate_pass)
			code = frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code")

			result = dispatch(code=code, device_info="gate-pass-scan")
			again = dispatch(code=code, device_info="gate-pass-scan-again")

		self.assertEqual(result["doctype"], "Purchase Receipt")
		receipt = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertEqual(again["name"], result["name"], "a re-scan reopens the same draft")
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name}), 1)

	def test_the_job_chain_creates_a_subcontracting_receipt_by_scan(self):
		with (
			with_gate_pass_mode(),
			integration_user_context(),
			patch_subcontracting_incoming_rate(5),
		):
			_order, asn = _submitted_job_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			_submit_by_flag("Gate Pass", gate_pass.name)
			code = get_or_create_scan_code(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)

			result = dispatch(code=code, device_info="job-gate-pass-scan")

		self.assertEqual(result["doctype"], "Subcontracting Receipt")
		self.assertEqual(frappe.db.get_value("Subcontracting Receipt", result["name"], "asn"), asn.name)
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name}), 0)

	def test_scanning_before_the_gate_pass_is_submitted_is_refused(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			code = get_or_create_scan_code(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)

			with self.assertRaises(frappe.ValidationError) as raised:
				dispatch(code=code, device_info="gate-pass-early")

		self.assertIn("submit the gate pass", str(raised.exception).lower())
		self.assertTrue(
			frappe.db.exists("Scan Log", {"scan_code": code, "result": "Failure"}),
			"the refused scan is logged",
		)

	def test_the_gate_pass_scan_requires_a_stock_role(self):
		email = ensure_integration_user("asn.chain.accounts@asn-module.test", roles=("Accounts User",))
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			_submit_by_flag("Gate Pass", gate_pass.name)
			code = get_or_create_scan_code(GATE_PASS_RECEIPT_ACTION, "Gate Pass", gate_pass.name)

		with integration_user_context(email), self.assertRaises(frappe.PermissionError):
			dispatch(code=code, device_info="gate-pass-no-stock")

	def test_cancelling_a_gate_pass_voids_its_code(self):
		with with_gate_pass_mode(), integration_user_context():
			_purchase_order, asn = _submitted_material_asn()
			gate_pass = _gate_pass_opened_by_scan(asn)
			_submit_by_flag("Gate Pass", gate_pass.name)
			on_gate_pass_submit(gate_pass)
			code = frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code")
			frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)

			on_gate_pass_cancel(SimpleNamespace(name=gate_pass.name))

			self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Voided")
			self.assertEqual(
				frappe.db.get_value("Gate Pass", gate_pass.name, "scan_code"),
				code,
				"a cancelled pass keeps its value",
			)
			with self.assertRaises(frappe.ValidationError) as raised:
				dispatch(code=code, device_info="gate-pass-cancelled")

		self.assertIn("not valid for scanning", str(raised.exception).lower())


class TestSubcontractingReceiptScanChain(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()
		block_commits_for_tests(cls)

	def _draft_subcontracting_receipt(self):
		handlers = TestSubcontractingHandlers()
		# A Purchase Receipt raised from a Subcontracting Receipt carries the
		# Purchase Order's non-stock service row, the way ERPNext's own flow
		# builds it, so give the fixture order a dedicated one instead of
		# flipping the shared stock item.
		service_item = handlers._ensure_item("_Test Subcontract PO Service Item", is_stock_item=0)
		subcontracting_order = handlers._make_integration_subcontracting_order(po_item_code=service_item)
		po_item = subcontracting_order.items[0].purchase_order_item
		# The mapper scales the receipt qty by fg_item_qty; the fixture
		# Purchase Order leaves it unset, so set it to the ordered qty for a
		# one-to-one mapping. The write rolls back with the test.
		po_item_qty = flt(frappe.db.get_value("Purchase Order Item", po_item, "qty"))
		frappe.db.set_value("Purchase Order Item", po_item, "fg_item_qty", po_item_qty, update_modified=False)

		from erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order import (
			make_subcontracting_receipt,
		)

		scr = make_subcontracting_receipt(subcontracting_order.name)
		# This bench mirrors production's mandatory Fiscal Year customisation on
		# Subcontracting Receipt; the scan handlers fill it, so this hand-rolled
		# draft must too or it dies on the missing mandatory field.
		fill_custom_fiscal_year(scr)
		scr.insert(ignore_permissions=True)
		return scr

	def test_submitting_a_subcontracting_receipt_attaches_the_purchase_receipt_codes(self):
		with patch_subcontracting_incoming_rate(5):
			scr = self._draft_subcontracting_receipt()
			on_subcontracting_receipt_submit(scr)

		code = _scan_code_for(SUBCONTRACTING_RECEIPT_PR_ACTION, "Subcontracting Receipt", scr.name)
		self.assertTrue(code)
		qr_name, barcode_name = _scan_code_attachment_names(code)
		files = _attached_file_names("Subcontracting Receipt", scr.name)
		self.assertIn(qr_name, files)
		self.assertIn(barcode_name, files)

	def test_scanning_a_subcontracting_receipt_opens_a_draft_purchase_receipt(self):
		with integration_user_context(), patch_subcontracting_incoming_rate(5):
			scr = self._draft_subcontracting_receipt()
			_submit_by_flag("Subcontracting Receipt", scr.name)
			code = get_or_create_scan_code(
				SUBCONTRACTING_RECEIPT_PR_ACTION, "Subcontracting Receipt", scr.name
			)

			result = dispatch(code=code, device_info="subcontracting-receipt-scan")
			again = dispatch(code=code, device_info="subcontracting-receipt-scan-again")

		self.assertEqual(result["doctype"], "Purchase Receipt")
		receipt = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.subcontracting_receipt, scr.name)
		self.assertEqual(again["name"], result["name"], "a re-scan reopens the same draft")
		self.assertEqual(
			frappe.db.count("Purchase Receipt", {"subcontracting_receipt": scr.name, "docstatus": 0}),
			1,
		)

	def test_scanning_refuses_an_unsubmitted_subcontracting_receipt(self):
		with integration_user_context(), patch_subcontracting_incoming_rate(5):
			scr = self._draft_subcontracting_receipt()
			code = get_or_create_scan_code(
				SUBCONTRACTING_RECEIPT_PR_ACTION, "Subcontracting Receipt", scr.name
			)

			with self.assertRaises(frappe.ValidationError) as raised:
				dispatch(code=code, device_info="subcontracting-receipt-early")

		self.assertIn("must be submitted", str(raised.exception).lower())

	def test_cancelling_a_subcontracting_receipt_voids_its_code(self):
		with integration_user_context(), patch_subcontracting_incoming_rate(5):
			scr = self._draft_subcontracting_receipt()
			_submit_by_flag("Subcontracting Receipt", scr.name)
			code = get_or_create_scan_code(
				SUBCONTRACTING_RECEIPT_PR_ACTION, "Subcontracting Receipt", scr.name
			)
			frappe.db.set_value("Scan Code", code, "status", "Used", update_modified=False)

			on_subcontracting_receipt_cancel(SimpleNamespace(name=scr.name))

			self.assertEqual(frappe.db.get_value("Scan Code", code, "status"), "Voided")
			with self.assertRaises(frappe.ValidationError):
				dispatch(code=code, device_info="subcontracting-receipt-cancelled")

	def test_the_handler_reopens_the_existing_draft_without_dispatch(self):
		with patch_subcontracting_incoming_rate(5):
			scr = self._draft_subcontracting_receipt()
			_submit_by_flag("Subcontracting Receipt", scr.name)

			first = create_receipt_from_subcontracting_receipt("Subcontracting Receipt", scr.name, {})
			second = create_receipt_from_subcontracting_receipt("Subcontracting Receipt", scr.name, {})

		self.assertEqual(second["name"], first["name"])


class TestUnlinkedReceiptGetsInvoiceCode(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()

	def test_a_receipt_without_an_asn_still_stores_the_purchase_invoice_code(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		with integration_user_context():
			purchase_order = create_purchase_order(qty=4)
			pr = make_purchase_receipt(purchase_order.name)
			for row in pr.items:
				row.warehouse = purchase_order.items[0].warehouse
			apply_receipt_site_requirements(pr)
			pr.insert(ignore_permissions=True)
			self.assertFalse(frappe.db.get_value("Purchase Receipt", pr.name, "scan_code"))
			pr.submit()

		code = _scan_code_for("create_purchase_invoice", "Purchase Receipt", pr.name)
		self.assertTrue(code, "an unlinked receipt carries the invoice code")
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "scan_code"), code)
		self.assertEqual(_attached_file_names("Purchase Receipt", pr.name), [])
