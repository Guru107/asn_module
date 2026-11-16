import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.document import Document
from frappe.permissions import add_permission, update_permission_property
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from asn_module.asn_module.doctype.asn.asn import ASN
from asn_module.asn_module.doctype.asn.test_asn import (
	_ensure_other_supplier,
	_other_uom,
	create_purchase_order,
	make_test_asn,
)
from asn_module.custom_fields.gate_pass import setup as setup_gate_pass_fields
from asn_module.handlers.gate_pass_create import create_from_gate_pass
from asn_module.handlers.purchase_invoice import create_from_purchase_receipt
from asn_module.handlers.purchase_receipt import (
	ASN_GATE_PASS_SCAN_ACTION,
	_apply_gate_pass_qty_to_subcontracting_receipt,
	_apply_shipped_qty_to_subcontracting_receipt,
	_get_single_purchase_order,
	_reopen_uncancelled_gate_pass,
	_set_if_present,
	asn_dispatch_action_key,
	create_gate_pass_from_asn,
	create_receipt_from_gate_pass,
	stamp_receipt_built_by_gate_pass,
)
from asn_module.handlers.subcontracting import (
	on_subcontracting_receipt_before_submit,
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
from asn_module.stock_cap.fetch import _fetch_in_transit
from asn_module.templates.pages import asn_new
from asn_module.templates.pages.asn_new_services import PortalValidationError, create_job_asn_for_supplier
from asn_module.tests.integration.fixtures import (
	ensure_integration_user,
	integration_user_context,
	with_gate_pass_mode,
)
from asn_module.utils.test_setup import before_tests


class TestAsnOrderIdentity(FrappeTestCase):
	def test_save_refuses_a_notice_that_mixes_a_purchase_order_and_a_subcontracting_order(self):
		purchase_order = create_purchase_order(qty=2)
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		asn = make_test_asn(purchase_order=purchase_order, qty=1)
		asn.append(
			"items",
			{
				"subcontracting_order": subcontracting_order.name,
				"subcontracting_order_item": finished_good.name,
				"item_code": finished_good.item_code,
				"qty": 1,
				"uom": finished_good.stock_uom,
				"rate": finished_good.rate,
			},
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("one order", str(raised.exception).lower())

	def test_save_refuses_a_notice_that_references_two_orders(self):
		first_order = create_purchase_order(qty=2)
		second_order = create_purchase_order(qty=2)
		second_line = second_order.items[0]
		asn = make_test_asn(purchase_order=first_order, qty=1)
		asn.append(
			"items",
			{
				"purchase_order": second_order.name,
				"purchase_order_item": second_line.name,
				"item_code": second_line.item_code,
				"qty": 1,
				"uom": second_line.uom,
				"rate": second_line.rate,
			},
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("one order", str(raised.exception).lower())

	def test_save_refuses_a_line_that_names_both_orders(self):
		purchase_order = create_purchase_order(qty=2)
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		asn = make_test_asn(purchase_order=purchase_order, qty=1)
		finished_good = subcontracting_order.items[0]
		asn.items[0].subcontracting_order = subcontracting_order.name
		asn.items[0].subcontracting_order_item = finished_good.name

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("one order", str(raised.exception).lower())

	def test_save_refuses_a_purchase_order_line_that_is_missing_the_order_line(self):
		asn = make_test_asn()
		asn.items[0].purchase_order_item = ""

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("order line", str(raised.exception).lower())

	def _job_asn_row(self, subcontracting_order):
		finished_good = subcontracting_order.items[0]
		asn = make_test_asn()
		asn.supplier = subcontracting_order.supplier
		asn.items = []
		asn.append(
			"items",
			{
				"subcontracting_order": subcontracting_order.name,
				"subcontracting_order_item": finished_good.name,
				"item_code": finished_good.item_code,
				"qty": 1,
				"uom": finished_good.stock_uom,
				"rate": finished_good.rate,
			},
		)
		return asn, finished_good

	def test_save_refuses_a_job_line_of_another_suppliers_order(self):
		asn, _finished_good = self._job_asn_row(
			TestSubcontractingHandlers()._make_integration_subcontracting_order()
		)
		asn.supplier = _ensure_other_supplier()

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("Row 1: Supplier _Test ASN Other Supplier does not match", str(raised.exception))

	def test_save_refuses_a_job_line_that_belongs_to_another_order(self):
		first_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		other_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		asn, _finished_good = self._job_asn_row(first_order)
		asn.items[0].subcontracting_order = other_order.name

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("Row 1: Subcontracting Order line", str(raised.exception))
		self.assertIn(f"belongs to {first_order.name}, not {other_order.name}", str(raised.exception))

	def test_save_refuses_a_job_line_whose_item_differs_from_the_order_line(self):
		asn, finished_good = self._job_asn_row(
			TestSubcontractingHandlers()._make_integration_subcontracting_order()
		)
		asn.items[0].item_code = make_test_asn().items[0].item_code

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(f"does not match {finished_good.item_code}", str(raised.exception))

	def test_save_refuses_a_job_line_whose_uom_differs_from_the_order_line(self):
		asn, finished_good = self._job_asn_row(
			TestSubcontractingHandlers()._make_integration_subcontracting_order()
		)
		wrong_uom = _other_uom(finished_good.stock_uom)
		asn.items[0].uom = wrong_uom

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: UOM {wrong_uom} does not match {finished_good.stock_uom}", str(raised.exception)
		)

	def test_save_refuses_a_job_line_of_a_draft_order(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		asn, _finished_good = self._job_asn_row(subcontracting_order)
		frappe.db.set_value(
			"Subcontracting Order",
			subcontracting_order.name,
			{"docstatus": 0, "status": "Draft"},
			update_modified=False,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: Subcontracting Order {subcontracting_order.name} is Draft, not open",
			str(raised.exception),
		)

	def test_save_refuses_a_job_line_of_a_closed_order(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		asn, _finished_good = self._job_asn_row(subcontracting_order)
		frappe.db.set_value("Subcontracting Order", subcontracting_order.name, "status", "Closed")

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn(
			f"Row 1: Subcontracting Order {subcontracting_order.name} is Closed, not open",
			str(raised.exception),
		)

	def test_save_refuses_a_subcontracting_order_line_that_is_missing_the_order(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		asn = make_test_asn()
		asn.items = []
		asn.append(
			"items",
			{
				"subcontracting_order_item": finished_good.name,
				"item_code": finished_good.item_code,
				"qty": 1,
				"uom": finished_good.stock_uom,
				"rate": finished_good.rate,
			},
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			asn.insert(ignore_permissions=True)

		self.assertIn("order line", str(raised.exception).lower())


class TestJobAsnPortal(FrappeTestCase):
	def test_supplier_portal_raises_a_job_asn_against_one_open_subcontracting_order(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		shipped_qty = 1

		asn = create_job_asn_for_supplier(
			supplier=subcontracting_order.supplier,
			subcontracting_order=subcontracting_order.name,
			header={
				"supplier_invoice_no": f"JOB-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": shipped_qty * finished_good.rate,
			},
			lines=[{"subcontracting_order_item": finished_good.name, "qty": shipped_qty}],
		)

		self.assertEqual(asn.supplier, subcontracting_order.supplier)
		self.assertEqual(len(asn.items), 1)
		line = asn.items[0]
		self.assertEqual(line.subcontracting_order, subcontracting_order.name)
		self.assertEqual(line.subcontracting_order_item, finished_good.name)
		self.assertEqual(line.qty, shipped_qty)
		self.assertEqual(line.item_code, finished_good.item_code)
		self.assertFalse(line.purchase_order)
		self.assertFalse(line.purchase_order_item)

	def test_omitted_lines_use_the_remaining_finished_good_qty(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		remaining = flt(finished_good.qty) - flt(finished_good.received_qty)

		asn = create_job_asn_for_supplier(
			supplier=subcontracting_order.supplier,
			subcontracting_order=subcontracting_order.name,
			header={
				"supplier_invoice_no": f"JOB-REST-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": remaining * finished_good.rate,
			},
		)

		self.assertEqual(asn.items[0].qty, remaining)

	def test_refuses_a_blank_closed_foreign_or_unknown_order_line(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		header = {
			"supplier_invoice_no": f"JOB-BAD-{frappe.generate_hash(length=8)}",
			"supplier_invoice_date": today(),
			"vehicle_number": "MH12AB1234",
			"supplier_invoice_amount": 1,
		}
		with self.assertRaises(frappe.ValidationError):
			create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=" ",
				header=header,
			)

		frappe.db.set_value("Subcontracting Order", subcontracting_order.name, "status", "Closed")
		with self.assertRaises(frappe.ValidationError):
			create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header=header,
			)
		frappe.db.set_value("Subcontracting Order", subcontracting_order.name, "status", "Open")

		with self.assertRaises(frappe.ValidationError):
			create_job_asn_for_supplier(
				supplier="Another Supplier",
				subcontracting_order=subcontracting_order.name,
				header=header,
			)
		with self.assertRaises(frappe.ValidationError):
			create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header=header,
				lines=[{"subcontracting_order_item": "missing-line", "qty": 1}],
			)

	def _posted_form(self, fields: dict):
		form = _PostedForm(fields)
		return (
			patch.object(asn_new.frappe, "form_dict", form),
			patch.object(asn_new.frappe, "request", SimpleNamespace(form=form, files={})),
		)

	def test_the_single_form_refuses_a_purchase_order_and_a_subcontracting_order_together(self):
		form_patch, request_patch = self._posted_form(
			{
				"subcontracting_order": "SCO-0001",
				"selected_purchase_orders": ["PO-0001"],
			}
		)
		with form_patch, request_patch, self.assertRaises(PortalValidationError) as raised:
			asn_new._create_single_asn("_Test Supplier")

		self.assertIn("both", str(raised.exception).lower())

	def test_the_single_form_raises_a_job_asn_from_the_posted_order(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		form_patch, request_patch = self._posted_form(
			{
				"subcontracting_order": subcontracting_order.name,
				"supplier_invoice_no": f"JOB-FORM-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": str(finished_good.rate),
				"subcontracting_order_item": [finished_good.name, ""],
				"job_asn_qty": ["1"],
			}
		)
		with form_patch, request_patch:
			result = asn_new._create_single_asn(subcontracting_order.supplier)

		asn = frappe.get_doc("ASN", result.asn_names[0])
		self.assertEqual(asn.items[0].subcontracting_order, subcontracting_order.name)
		self.assertEqual(asn.items[0].qty, 1)
		self.assertFalse(result.incomplete)

	def test_saving_the_posted_job_draft_again_updates_that_draft(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		invoice_no = f"JOB-RESUME-{frappe.generate_hash(length=8)}"
		first_form, first_request = self._posted_form(
			{
				"subcontracting_order": subcontracting_order.name,
				"supplier_invoice_no": invoice_no,
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": str(finished_good.rate),
				"subcontracting_order_item": [finished_good.name],
				"job_asn_qty": ["1"],
			}
		)
		with first_form, first_request:
			created = asn_new._create_single_asn(subcontracting_order.supplier)

		second_form, second_request = self._posted_form(
			{
				"asn_name": created.asn_names[0],
				"subcontracting_order": subcontracting_order.name,
				"supplier_invoice_no": invoice_no,
				"supplier_invoice_date": today(),
				"vehicle_number": "MH01CD5678",
				"supplier_invoice_amount": str(finished_good.rate),
				"subcontracting_order_item": [finished_good.name],
				"job_asn_qty": ["1"],
			}
		)
		with second_form, second_request:
			updated = asn_new._create_single_asn(subcontracting_order.supplier)

		self.assertEqual(updated.asn_names, created.asn_names)
		asn = frappe.get_doc("ASN", created.asn_names[0])
		self.assertEqual(asn.vehicle_number, "MH01CD5678")
		self.assertEqual(
			frappe.db.count(
				"ASN", {"supplier": subcontracting_order.supplier, "supplier_invoice_no": invoice_no}
			),
			1,
		)

	def test_shipped_qty_above_the_remaining_finished_good_qty_is_refused(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		remaining = flt(finished_good.qty) - flt(finished_good.received_qty)
		with self.assertRaises(frappe.ValidationError) as raised:
			create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header={
					"supplier_invoice_no": f"JOB-OVER-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"vehicle_number": "MH12AB1234",
					"supplier_invoice_amount": 1,
				},
				lines=[{"subcontracting_order_item": finished_good.name, "qty": remaining + 1}],
			)

		self.assertIn("remaining", str(raised.exception).lower())

	def test_a_duplicate_subcontracting_order_line_is_refused(self):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		with self.assertRaises(frappe.ValidationError) as raised:
			create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header={
					"supplier_invoice_no": f"JOB-DUP-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"vehicle_number": "MH12AB1234",
					"supplier_invoice_amount": 1,
				},
				lines=[
					{"subcontracting_order_item": finished_good.name, "qty": 1},
					{"subcontracting_order_item": finished_good.name, "qty": 1},
				],
			)

		self.assertIn("duplicate", str(raised.exception).lower())

	def test_shipped_qty_equal_to_the_remaining_qty_is_not_refused_by_float_noise(self):
		# 0.3 - 0.1 is 0.19999999999999998 as a raw float.
		asn = SimpleNamespace(items=[SimpleNamespace(idx=1, subcontracting_order_item="SCO-ITEM-1", qty=0.2)])
		order_line = frappe._dict(name="SCO-ITEM-1", qty=0.3, received_qty=0.1)
		with patch.object(frappe, "get_all", return_value=[order_line]):
			ASN._validate_subcontracting_lines(asn)


class _PostedForm(dict):
	def getlist(self, fieldname):
		value = self.get(fieldname, [])
		if isinstance(value, list):
			return value
		return [value]


class TestJobAsnScan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()

	def test_scanning_a_job_asn_opens_a_draft_subcontracting_receipt_for_the_shipped_qty(self):
		with with_gate_pass_mode(False):
			subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
			finished_good = subcontracting_order.items[0]
			shipped_qty = 1
			asn = create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header={
					"supplier_invoice_no": f"JOB-SCAN-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"vehicle_number": "MH12AB1234",
					"supplier_invoice_amount": shipped_qty * finished_good.rate,
				},
				lines=[{"subcontracting_order_item": finished_good.name, "qty": shipped_qty}],
			)
			asn.submit()

			code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				first = dispatch(code=code, device_info="job-asn")
				reopened = create_gate_pass_from_asn("ASN", asn.name, {})
				second = dispatch(code=code, device_info="job-asn-again")

		self.assertEqual(first["doctype"], "Subcontracting Receipt")
		self.assertEqual(reopened["name"], first["name"])
		self.assertEqual(second["name"], first["name"])
		receipt = frappe.get_doc("Subcontracting Receipt", first["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertEqual(receipt.items[0].qty, shipped_qty)
		self.assertEqual(receipt.items[0].item_code, finished_good.item_code)
		self.assertEqual(
			frappe.db.count("Subcontracting Receipt", {"asn": asn.name, "docstatus": 0}),
			1,
		)


def submit_subcontracting_receipt_hooks(receipt) -> None:
	"""Run the module's submit hooks on a draft receipt and mark it submitted.

	A real submit needs raw materials at the supplier; the hooks are what is under test.
	"""
	on_subcontracting_receipt_before_submit(receipt)
	frappe.db.set_value("Subcontracting Receipt", receipt.name, "docstatus", 1, update_modified=False)
	receipt.docstatus = 1
	on_subcontracting_receipt_submit(receipt)


class TestJobAsnReceiptTracking(FrappeTestCase):
	"""A Subcontracting Receipt updates its Job ASN as a linked Purchase Receipt does."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()

	def _scanned_receipt(self, shipped_qty: float):
		"""A submitted Job ASN shipping ``shipped_qty`` and the draft receipt its scan opens."""
		order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = order.items[0]
		# The fixture orders 2; raise it so the ASN can ship the qty under test.
		frappe.db.set_value(
			"Subcontracting Order Item", finished_good.name, "qty", shipped_qty, update_modified=False
		)
		asn = create_job_asn_for_supplier(
			supplier=order.supplier,
			subcontracting_order=order.name,
			header={
				"supplier_invoice_no": f"JOB-RCV-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": shipped_qty * finished_good.rate,
			},
			lines=[{"subcontracting_order_item": finished_good.name, "qty": shipped_qty}],
		)
		asn.submit()
		code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		with with_gate_pass_mode(False), integration_user_context(), patch_subcontracting_incoming_rate(5):
			result = dispatch(code=code, device_info="job-asn-receipt")
		return asn, code, finished_good, frappe.get_doc("Subcontracting Receipt", result["name"])

	def _in_transit(self, finished_good) -> float:
		branch_by_warehouse = {finished_good.warehouse: "_Test Job ASN Branch"}
		totals = _fetch_in_transit([finished_good.item_code], [finished_good.warehouse], branch_by_warehouse)
		return flt(totals.get(("_Test Job ASN Branch", finished_good.item_code)))

	def test_a_full_receipt_marks_the_job_asn_received_and_a_rescan_creates_nothing(self):
		asn, code, finished_good, receipt = self._scanned_receipt(shipped_qty=10)
		asn_item = asn.items[0].name
		self.assertEqual(
			json.loads(receipt.asn_items)[receipt.items[0].name]["asn_item_name"],
			asn_item,
			"the scan stores the receipt row to ASN line map",
		)
		in_transit_before = self._in_transit(finished_good)

		submit_subcontracting_receipt_hooks(receipt)

		self.assertEqual(flt(frappe.db.get_value("ASN Item", asn_item, "received_qty")), 10)
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Received")
		self.assertEqual(self._in_transit(finished_good), in_transit_before - 10)
		self.assertTrue(
			frappe.db.exists(
				"ASN Transition Log",
				{"asn_item": asn_item, "state": "SCR_SUBMITTED", "ref_name": receipt.name},
			)
		)
		with with_gate_pass_mode(False), integration_user_context():
			with self.assertRaisesRegex(frappe.ValidationError, "Cannot create Subcontracting Receipt"):
				dispatch(code=code, device_info="job-asn-rescan")
		self.assertEqual(frappe.db.count("Subcontracting Receipt", {"asn": asn.name}), 1)

	def test_cancelling_the_receipt_takes_the_qty_back_and_reopens_the_job_asn(self):
		asn, _code, finished_good, receipt = self._scanned_receipt(shipped_qty=10)
		in_transit_before = self._in_transit(finished_good)
		submit_subcontracting_receipt_hooks(receipt)

		frappe.db.set_value("Subcontracting Receipt", receipt.name, "docstatus", 2, update_modified=False)
		receipt.docstatus = 2
		on_subcontracting_receipt_cancel(receipt)

		self.assertEqual(flt(frappe.db.get_value("ASN Item", asn.items[0].name, "received_qty")), 0)
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Submitted")
		self.assertEqual(self._in_transit(finished_good), in_transit_before)

	def test_a_short_receipt_closes_the_job_asn(self):
		asn, _code, finished_good, receipt = self._scanned_receipt(shipped_qty=10)
		in_transit_before = self._in_transit(finished_good)
		receipt.items[0].qty = 8
		receipt.items[0].received_qty = 8
		with patch_subcontracting_incoming_rate(5):
			receipt.save()

		submit_subcontracting_receipt_hooks(receipt)

		self.assertEqual(flt(frappe.db.get_value("ASN Item", asn.items[0].name, "received_qty")), 8)
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Closed")
		# A Closed ASN holds nothing in transit, not even the 2 that never arrived.
		self.assertEqual(self._in_transit(finished_good), in_transit_before - 10)


def ensure_mandatory_fiscal_year_custom_field() -> None:
	"""Give the scan a mandatory Fiscal Year to satisfy.

	Production marks a ``custom_fiscal_year`` Link mandatory on Subcontracting Receipt.
	This bench mirrors production customisations, but that field is newer than the
	bench's last production sync, so the scan path has never met it here. The scan
	builds receipts server-side, where no desk form ever fills the field, so the bench
	must carry the same customisation to keep that path honest. Guarded: a site that
	already requires the field is left exactly as it is.
	"""
	meta = frappe.get_meta("Subcontracting Receipt")
	field = meta.get_field("custom_fiscal_year")
	if field and field.reqd:
		return

	create_custom_fields(
		{
			"Subcontracting Receipt": [
				{
					"fieldname": "custom_fiscal_year",
					"label": "Fiscal Year",
					"fieldtype": "Link",
					"options": "Fiscal Year",
					"reqd": 1,
					"insert_after": "posting_date",
				},
			],
		}
	)
	frappe.clear_cache(doctype="Subcontracting Receipt")


class TestJobAsnScanWithMandatoryFiscalYear(FrappeTestCase):
	"""The scan must satisfy a site's mandatory Fiscal Year on the receipts it builds.

	Deleting the draft receipt used to be enough to expose this: while a draft exists
	the scan reopens it, and only the create path ever meets the mandatory field.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()
		ensure_mandatory_fiscal_year_custom_field()

	def test_scanning_a_job_asn_fills_the_sites_mandatory_fiscal_year(self):
		with with_gate_pass_mode(False):
			subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
			finished_good = subcontracting_order.items[0]
			asn = create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header={
					"supplier_invoice_no": f"JOB-FY-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"vehicle_number": "MH12AB1234",
					"supplier_invoice_amount": finished_good.rate,
				},
				lines=[{"subcontracting_order_item": finished_good.name, "qty": 1}],
			)
			asn.submit()

			code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				result = dispatch(code=code, device_info="job-asn-fy")

		receipt = frappe.get_doc("Subcontracting Receipt", result["name"])
		# Several test fiscal years can cover the same posting date (they overlap
		# by design), so don't pin the exact pick: assert the scan filled the
		# mandatory link with an enabled Fiscal Year covering the posting date.
		chosen = frappe.db.get_value(
			"Fiscal Year",
			receipt.custom_fiscal_year,
			["disabled", "year_start_date", "year_end_date"],
			as_dict=True,
		)
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertIsNotNone(chosen, "custom_fiscal_year names a real Fiscal Year")
		self.assertFalse(chosen.disabled)
		self.assertTrue(chosen.year_start_date <= receipt.posting_date <= chosen.year_end_date)


def ensure_gate_pass_for_tests() -> None:
	"""Give the scan a Gate Pass to save.

	CI has no Gate Pass, so this builds the production custom DocType's shape:
	its required fields, link types and the ``items`` / ``item`` tables.
	"""
	if not frappe.db.exists("DocType", "Gate Pass Item"):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": "Gate Pass Item",
				"module": "Custom",
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "item_code", "fieldtype": "Link", "options": "Item", "label": "Item Code"},
					{"fieldname": "uom", "fieldtype": "Link", "options": "UOM", "label": "UOM"},
					{"fieldname": "rate", "fieldtype": "Currency", "label": "Rate"},
					{
						"fieldname": "purchase_order_item",
						"fieldtype": "Data",
						"label": "Purchase Order Item",
					},
					{"fieldname": "qty", "fieldtype": "Float", "label": "Qty"},
					{"fieldname": "pending_qty", "fieldtype": "Float", "label": "Pending Qty"},
					{"fieldname": "receive_qty", "fieldtype": "Float", "label": "Receive Qty"},
				],
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("DocType", "Gate Pass Type"):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": "Gate Pass Type",
				"module": "Custom",
				"custom": 1,
				"autoname": "field:gate_pass_type",
				"naming_rule": "By fieldname",
				"fields": [
					{
						"fieldname": "gate_pass_type",
						"fieldtype": "Data",
						"label": "Gate Pass Type",
						"reqd": 1,
						"unique": 1,
					}
				],
				"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Gate Pass Type", "Material"):
		frappe.get_doc({"doctype": "Gate Pass Type", "gate_pass_type": "Material"}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("Gate Pass Type", "Job"):
		frappe.get_doc({"doctype": "Gate Pass Type", "gate_pass_type": "Job"}).insert(ignore_permissions=True)

	if not frappe.db.exists("DocType", "Gate Pass Item Table"):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": "Gate Pass Item Table",
				"module": "Custom",
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "item_code", "fieldtype": "Link", "options": "Item", "label": "Item Code"},
					{
						"fieldname": "subcontracting_order_item",
						"fieldtype": "Data",
						"label": "Subcontracting Order Item",
					},
					{"fieldname": "qty", "fieldtype": "Float", "label": "Qty"},
					{"fieldname": "pending_qty", "fieldtype": "Float", "label": "Pending Qty"},
				],
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("DocType", "Gate Pass"):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": "Gate Pass",
				"module": "Custom",
				"custom": 1,
				"fields": [
					{
						"fieldname": "entry_type",
						"fieldtype": "Select",
						"options": "\nGate In\nGate Out",
						"label": "Entry Type",
						"reqd": 1,
					},
					{
						"fieldname": "gate_pass_type",
						"fieldtype": "Link",
						"options": "Gate Pass Type",
						"label": "Gate Pass Type",
						"reqd": 1,
					},
					{
						"fieldname": "document_reference",
						"fieldtype": "Link",
						"options": "DocType",
						"label": "Document Reference",
					},
					{
						"fieldname": "reference_number",
						"fieldtype": "Dynamic Link",
						"options": "document_reference",
						"label": "Reference Number",
					},
					{"fieldname": "company", "fieldtype": "Link", "options": "Company", "label": "Company"},
					{
						"fieldname": "supplier",
						"fieldtype": "Link",
						"options": "Supplier",
						"label": "Supplier",
					},
					{
						"fieldname": "vehicle_number",
						"fieldtype": "Data",
						"label": "Vehicle Number",
						"reqd": 1,
					},
					{"fieldname": "invoice_number", "fieldtype": "Data", "label": "Invoice Number"},
					{"fieldname": "invoice_date", "fieldtype": "Date", "label": "Invoice Date"},
					{"fieldname": "challan_number", "fieldtype": "Data", "label": "Challan Number"},
					{"fieldname": "challan_date", "fieldtype": "Date", "label": "Challan Date"},
					{"fieldname": "asn", "fieldtype": "Link", "options": "ASN", "label": "ASN"},
					{
						"fieldname": "items",
						"fieldtype": "Table",
						"options": "Gate Pass Item",
						"label": "Items",
					},
					{
						"fieldname": "item",
						"fieldtype": "Table",
						"options": "Gate Pass Item Table",
						"label": "Item",
					},
				],
				"permissions": [
					{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
					{"role": "Stock User", "read": 1, "write": 1, "create": 1},
					{"role": "Stock Manager", "read": 1, "write": 1, "create": 1},
				],
			}
		).insert(ignore_permissions=True)

	meta = frappe.get_meta("Gate Pass")
	custom_fields = []
	if not meta.has_field("asn"):
		custom_fields.append(
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"options": "ASN",
				"label": "ASN",
				"insert_after": "supplier",
			}
		)
	if custom_fields:
		create_custom_fields({"Gate Pass": custom_fields})
		frappe.clear_cache(doctype="Gate Pass")
	# The scan inserts the Gate Pass as the scanning user. Production grants Stock User via Custom DocPerm.
	for role in ("Stock User", "Stock Manager"):
		if not any(perm.role == role and perm.create for perm in meta.permissions):
			add_permission("Gate Pass", role)
			for ptype in ("write", "create"):
				update_permission_property("Gate Pass", role, 0, ptype, 1)
	# The module's own Scan Code field, as after_migrate adds it on a real site.
	setup_gate_pass_fields()
	frappe.clear_cache(doctype="Gate Pass")


_ASN_DRAFT_DOCTYPES = ("Gate Pass", "Purchase Receipt", "Subcontracting Receipt")


@contextmanager
def _second_scan_with_a_stale_snapshot():
	"""Replay the losing side of two simultaneous scans of one ASN.

	Under REPEATABLE READ the second scan's plain reads use a snapshot taken before the
	first scan committed its draft, so they miss it. Only a locking read sees it.
	"""
	real_get_value = frappe.db.get_value
	real_get_all = frappe.get_all

	def hides_draft(doctype, filters) -> bool:
		return doctype in _ASN_DRAFT_DOCTYPES and isinstance(filters, dict) and "asn" in filters

	def get_value(doctype, filters=None, *args, **kwargs):
		if not kwargs.get("for_update") and hides_draft(doctype, filters):
			return None
		return real_get_value(doctype, filters, *args, **kwargs)

	def get_all(doctype, *args, **kwargs):
		if hides_draft(doctype, kwargs.get("filters")):
			return []
		return real_get_all(doctype, *args, **kwargs)

	with (
		patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", side_effect=get_value),
		patch("asn_module.handlers.purchase_receipt.frappe.get_all", side_effect=get_all),
		patch("asn_module.handlers.purchase_receipt.frappe.get_doc", wraps=frappe.get_doc) as get_doc,
	):
		yield get_doc


class TestMaterialGatePassScan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()
		ensure_gate_pass_for_tests()

	def test_submitted_asn_scan_code_uses_gate_pass_action_when_mode_is_on(self):
		with with_gate_pass_mode(True):
			self.assertEqual(asn_dispatch_action_key(), ASN_GATE_PASS_SCAN_ACTION)
			purchase_order = create_purchase_order(qty=2)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"GP-QR-{frappe.generate_hash(length=8)}",
				qty=2,
			)
			asn.insert(ignore_permissions=True)
			asn.submit()

		action_key = frappe.db.get_value(
			"Scan Code",
			{"source_doctype": "ASN", "source_name": asn.name},
			"action_key",
		)
		self.assertEqual(action_key, ASN_GATE_PASS_SCAN_ACTION)

	def test_scanning_a_material_asn_with_gate_pass_mode_on_opens_a_draft_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				purchase_order = create_purchase_order(qty=4)
				shipped_qty = 2
				asn = make_test_asn(
					purchase_order=purchase_order,
					supplier_invoice_no=f"GP-ON-{frappe.generate_hash(length=8)}",
					qty=shipped_qty,
				)
				asn.insert(ignore_permissions=True)
				asn.submit()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				result = dispatch(code=code, device_info="gate-pass-on")

		self.assertEqual(result["action"], ASN_GATE_PASS_SCAN_ACTION)
		self.assertEqual(result["doctype"], "Gate Pass")
		gate_pass = frappe.get_doc("Gate Pass", result["name"])
		self.assertEqual(gate_pass.docstatus, 0)
		self.assertEqual(gate_pass.asn, asn.name)
		self.assertEqual(gate_pass.entry_type, "Gate In")
		self.assertEqual(gate_pass.gate_pass_type, "Material")
		self.assertEqual(gate_pass.document_reference, "Purchase Order")
		self.assertEqual(gate_pass.reference_number, purchase_order.name)
		self.assertEqual(gate_pass.company, purchase_order.company)
		self.assertEqual(gate_pass.supplier, asn.supplier)
		self.assertEqual(gate_pass.vehicle_number, asn.vehicle_number)
		self.assertEqual(gate_pass.invoice_number, asn.supplier_invoice_no)
		self.assertEqual(str(gate_pass.invoice_date), str(asn.supplier_invoice_date))
		self.assertEqual(gate_pass.challan_number, asn.supplier_invoice_no)
		self.assertEqual(str(gate_pass.challan_date), str(asn.supplier_invoice_date))
		self.assertEqual(len(gate_pass.items), 1)
		line = gate_pass.items[0]
		order_line = purchase_order.items[0]
		self.assertEqual(line.item_code, order_line.item_code)
		self.assertEqual(line.uom, order_line.uom)
		self.assertEqual(flt(line.rate), flt(order_line.rate))
		self.assertEqual(line.purchase_order_item, order_line.name)
		self.assertEqual(flt(line.qty), flt(order_line.qty))
		self.assertEqual(flt(line.receive_qty), flt(shipped_qty))
		self.assertEqual(flt(line.pending_qty), flt(order_line.qty) - flt(order_line.received_qty))

	def _submitted_material_asn(self):
		purchase_order = create_purchase_order(qty=4)
		asn = make_test_asn(
			purchase_order=purchase_order,
			supplier_invoice_no=f"GP-ON-{frappe.generate_hash(length=8)}",
			qty=2,
		)
		asn.insert(ignore_permissions=True)
		asn.submit()
		return purchase_order, asn

	def test_deleting_a_draft_row_before_submit_credits_each_asn_line_its_own_qty(self):
		"""The desk renumbers rows when a draft is edited; the row-to-line map must
		follow the row, not its position."""
		with with_gate_pass_mode(False):
			purchase_order = create_purchase_order(item_count=3, unique_items=True, qty=6)
			asn = frappe.get_doc(
				{
					"doctype": "ASN",
					"supplier": purchase_order.supplier,
					"supplier_invoice_no": f"MAP-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"expected_delivery_date": today(),
					"supplier_invoice_amount": sum(
						flt(row.qty) * flt(row.rate) for row in purchase_order.items
					),
					"vehicle_number": "MH12AB1234",
					"items": [
						{
							"purchase_order": purchase_order.name,
							"purchase_order_item": po_item.name,
							"item_code": po_item.item_code,
							"qty": qty,
							"uom": po_item.uom,
							"rate": po_item.rate,
						}
						for qty, po_item in zip((2, 3, 4), purchase_order.items, strict=True)
					],
				}
			)
			asn.insert(ignore_permissions=True)
			asn.submit()
			with integration_user_context():
				created = create_gate_pass_from_asn("ASN", asn.name, {})

		self.assertEqual(created["doctype"], "Purchase Receipt")
		receipt = frappe.get_doc("Purchase Receipt", created["name"])
		self.assertEqual(len(receipt.items), 3)
		removed_asn_item = asn.items[0].name
		kept_asn_items = [(row.name, row.qty) for row in asn.items[1:]]

		# The desk deletes the first row and renumbers the rest before submitting.
		receipt.items.pop(0)
		for pos, row in enumerate(receipt.items, start=1):
			row.idx = pos
		receipt.save(ignore_permissions=True)
		with (
			patch("asn_module.handlers.purchase_receipt.store_scan_code"),
		):
			receipt.submit()

		self.assertEqual(flt(frappe.db.get_value("ASN Item", removed_asn_item, "received_qty")), 0)
		for asn_item_name, expected_qty in kept_asn_items:
			self.assertEqual(
				flt(frappe.db.get_value("ASN Item", asn_item_name, "received_qty")), flt(expected_qty)
			)

	def test_a_later_scan_opens_the_same_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				first = dispatch(code=code, device_info="gate-pass-on")
				second = dispatch(code=code, device_info="gate-pass-on-again")

		self.assertEqual(first["doctype"], "Gate Pass")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_cancelled_gate_pass_does_not_block_a_new_draft(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				first = dispatch(code=code, device_info="gate-pass-on")
				frappe.db.set_value("Gate Pass", first["name"], "docstatus", 2, update_modified=False)
				second = dispatch(code=code, device_info="gate-pass-after-cancel")

		self.assertEqual(second["doctype"], "Gate Pass")
		self.assertNotEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.get_value("Gate Pass", second["name"], "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Gate Pass", second["name"], "asn"), asn.name)
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_draft_purchase_receipt_wins_over_a_gate_pass(self):
		with with_gate_pass_mode(False) as mode:
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				receipt = create_gate_pass_from_asn("ASN", asn.name, {})
				mode.set(True)
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-on-existing-receipt")

		self.assertEqual(opened["doctype"], "Purchase Receipt")
		self.assertEqual(opened["name"], receipt["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 0)

	def _submitted_job_asn(self, shipped_qty=1):
		subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
		finished_good = subcontracting_order.items[0]
		asn = create_job_asn_for_supplier(
			supplier=subcontracting_order.supplier,
			subcontracting_order=subcontracting_order.name,
			header={
				"supplier_invoice_no": f"JOB-GP-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"vehicle_number": "MH12AB1234",
				"supplier_invoice_amount": shipped_qty * finished_good.rate,
			},
			lines=[{"subcontracting_order_item": finished_good.name, "qty": shipped_qty}],
		)
		asn.submit()
		return subcontracting_order, asn

	def test_scanning_a_job_asn_with_gate_pass_mode_on_opens_a_draft_job_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				subcontracting_order, asn = self._submitted_job_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				result = dispatch(code=code, device_info="job-gate-pass-on")

		finished_good = subcontracting_order.items[0]
		self.assertEqual(result["doctype"], "Gate Pass")
		gate_pass = frappe.get_doc("Gate Pass", result["name"])
		self.assertEqual(gate_pass.docstatus, 0)
		self.assertEqual(gate_pass.entry_type, "Gate In")
		self.assertEqual(gate_pass.gate_pass_type, "Job")
		self.assertEqual(gate_pass.document_reference, "Subcontracting Order")
		self.assertEqual(gate_pass.reference_number, subcontracting_order.name)
		self.assertEqual(gate_pass.company, subcontracting_order.company)
		self.assertEqual(gate_pass.vehicle_number, asn.vehicle_number)
		self.assertEqual(gate_pass.invoice_number, asn.supplier_invoice_no)
		self.assertEqual(str(gate_pass.invoice_date), str(asn.supplier_invoice_date))
		self.assertEqual(gate_pass.challan_number, asn.supplier_invoice_no)
		self.assertEqual(str(gate_pass.challan_date), str(asn.supplier_invoice_date))
		self.assertEqual(gate_pass.asn, asn.name)
		self.assertEqual(len(gate_pass.item), 1)
		self.assertEqual(gate_pass.item[0].subcontracting_order_item, finished_good.name)
		self.assertEqual(flt(gate_pass.item[0].qty), 1)
		self.assertEqual(
			flt(gate_pass.item[0].pending_qty),
			flt(finished_good.qty) - flt(finished_good.received_qty),
		)
		self.assertEqual(frappe.db.count("Subcontracting Receipt", {"asn": asn.name}), 0)
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name}), 0)

	def test_a_later_scan_opens_the_same_job_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				_order, asn = self._submitted_job_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				first = dispatch(code=code, device_info="job-gate-pass-on")
				second = dispatch(code=code, device_info="job-gate-pass-on-again")

		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_cancelled_job_gate_pass_does_not_block_a_new_draft(self):
		with with_gate_pass_mode(True):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				_order, asn = self._submitted_job_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				first = dispatch(code=code, device_info="job-gate-pass-on")
				frappe.db.set_value("Gate Pass", first["name"], "docstatus", 2, update_modified=False)
				second = dispatch(code=code, device_info="job-gate-pass-after-cancel")

		self.assertNotEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.get_value("Gate Pass", second["name"], "docstatus"), 0)

	def _scan_twice_concurrently(self, asn) -> tuple[dict, dict]:
		first = create_gate_pass_from_asn("ASN", asn.name, {})
		with _second_scan_with_a_stale_snapshot() as get_doc:
			second = create_gate_pass_from_asn("ASN", asn.name, {})
		# The row lock that makes the second scan wait for the first one's commit.
		get_doc.assert_any_call("ASN", asn.name, for_update=True)
		return first, second

	def test_a_concurrent_scan_reopens_the_gate_pass_the_first_scan_saved(self):
		with with_gate_pass_mode(True), integration_user_context():
			_purchase_order, asn = self._submitted_material_asn()
			first, second = self._scan_twice_concurrently(asn)

		self.assertEqual(first["doctype"], "Gate Pass")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_concurrent_scan_reopens_the_purchase_receipt_the_first_scan_saved(self):
		with with_gate_pass_mode(False), integration_user_context():
			_purchase_order, asn = self._submitted_material_asn()
			first, second = self._scan_twice_concurrently(asn)

		self.assertEqual(first["doctype"], "Purchase Receipt")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_concurrent_scan_reopens_the_subcontracting_receipt_the_first_scan_saved(self):
		with with_gate_pass_mode(False):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				_order, asn = self._submitted_job_asn()
				first, second = self._scan_twice_concurrently(asn)

		self.assertEqual(first["doctype"], "Subcontracting Receipt")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Subcontracting Receipt", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_subcontracting_order_receipt_code_stays_a_receipt(self):
		with with_gate_pass_mode(True):
			subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
			code = get_or_create_scan_code(
				"create_subcontracting_receipt",
				"Subcontracting Order",
				subcontracting_order.name,
			)
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				result = dispatch(code=code, device_info="sco-receipt-code")

		self.assertEqual(result["doctype"], "Subcontracting Receipt")
		self.assertFalse(frappe.db.get_value("Subcontracting Receipt", result["name"], "asn"))
		self.assertEqual(frappe.db.count("Gate Pass", {"reference_number": subcontracting_order.name}), 0)

	def test_create_from_gate_pass_uses_receive_qty_at_the_gate(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-receive-qty")
				gp_item = (frappe.get_doc("Gate Pass", opened["name"]).items or [None])[0]
				self.assertIsNotNone(gp_item)
				self.assertEqual(flt(gp_item.receive_qty), 2)
				frappe.db.set_value("Gate Pass Item", gp_item.name, "receive_qty", 1, update_modified=False)
				frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
				created = create_receipt_from_gate_pass(opened["name"])

		receipt = frappe.get_doc("Purchase Receipt", created["name"])
		self.assertEqual(flt(receipt.items[0].qty), 1)
		self.assertEqual(flt(receipt.items[0].received_qty), 1)

	def _submitted_gate_pass_for_two_lines_on_one_order_line(self) -> tuple[Document, str]:
		"""ASN with two lines (4 and 6) on one Purchase Order Item, through a submitted Gate Pass."""
		purchase_order = create_purchase_order(qty=10)
		po_item = purchase_order.items[0]
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": purchase_order.supplier,
				"supplier_invoice_no": f"GP-SPLIT-{frappe.generate_hash(length=8)}",
				"supplier_invoice_date": today(),
				"expected_delivery_date": today(),
				"supplier_invoice_amount": 10 * flt(po_item.rate),
				"vehicle_number": "MH12AB1234",
				"items": [
					{
						"purchase_order": purchase_order.name,
						"purchase_order_item": po_item.name,
						"item_code": po_item.item_code,
						"qty": qty,
						"uom": po_item.uom,
						"rate": po_item.rate,
					}
					for qty in (4, 6)
				],
			}
		)
		asn.insert(ignore_permissions=True)
		asn.submit()
		opened = create_gate_pass_from_asn("ASN", asn.name, {})
		frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
		return asn, opened["name"]

	def _assert_each_asn_line_gets_its_own_qty(self, asn: Document, receipt: Document) -> None:
		self.assertEqual(sorted(flt(row.qty) for row in receipt.items), [4, 6])
		with patch("asn_module.handlers.purchase_receipt.store_scan_code"):
			receipt.submit()
		for asn_item in asn.items:
			self.assertEqual(
				flt(frappe.db.get_value("ASN Item", asn_item.name, "received_qty")), flt(asn_item.qty)
			)

	def test_two_asn_lines_on_one_order_line_keep_their_own_qty_through_the_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				asn, gate_pass_name = self._submitted_gate_pass_for_two_lines_on_one_order_line()
				created = create_receipt_from_gate_pass(gate_pass_name)

		self._assert_each_asn_line_gets_its_own_qty(asn, frappe.get_doc("Purchase Receipt", created["name"]))

	def test_a_line_left_at_zero_at_the_gate_does_not_shift_qty_onto_it(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				asn, gate_pass_name = self._submitted_gate_pass_for_two_lines_on_one_order_line()
				first_row = frappe.get_doc("Gate Pass", gate_pass_name).items[0]
				frappe.db.set_value("Gate Pass Item", first_row.name, "receive_qty", 0, update_modified=False)
				created = create_receipt_from_gate_pass(gate_pass_name)

		receipt = frappe.get_doc("Purchase Receipt", created["name"])
		self.assertEqual([flt(row.qty) for row in receipt.items], [6])
		with patch("asn_module.handlers.purchase_receipt.store_scan_code"):
			receipt.submit()
		received = [flt(frappe.db.get_value("ASN Item", row.name, "received_qty")) for row in asn.items]
		self.assertEqual(received, [0, 6])

	def test_a_second_create_after_a_short_receipt_closed_the_asn_is_refused(self):
		# The CI Gate Pass has no custom_gate_pass_reference, so only the ASN status stops a second receipt.
		with with_gate_pass_mode(True):
			with integration_user_context():
				asn, gate_pass_name = self._submitted_gate_pass_for_two_lines_on_one_order_line()
				first_row = frappe.get_doc("Gate Pass", gate_pass_name).items[0]
				frappe.db.set_value("Gate Pass Item", first_row.name, "receive_qty", 0, update_modified=False)
				created = create_receipt_from_gate_pass(gate_pass_name)
			with patch("asn_module.handlers.purchase_receipt.store_scan_code"):
				frappe.get_doc("Purchase Receipt", created["name"]).submit()
			self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Closed")

			with (
				integration_user_context(),
				self.assertRaisesRegex(frappe.ValidationError, "Cannot create Purchase Receipt"),
			):
				create_receipt_from_gate_pass(gate_pass_name)

		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": ["!=", 2]}), 1)

	def test_desk_create_keeps_each_asn_lines_own_qty_on_insert(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				asn, gate_pass_name = self._submitted_gate_pass_for_two_lines_on_one_order_line()
				create_from_gate_pass(gate_pass_name)
				receipt = frappe.response.pop("message")
				# The stamp hook reads this link; set it where the site lacks the custom field.
				receipt.custom_gate_pass_reference = gate_pass_name
				fill_custom_fiscal_year(receipt)  # the desk form fills this before save
				receipt.insert(ignore_permissions=True)

		self.assertEqual(receipt.asn, asn.name)
		self._assert_each_asn_line_gets_its_own_qty(asn, receipt)

	def test_create_on_a_submitted_material_gate_pass_opens_a_purchase_receipt_carrying_the_asn(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				purchase_order = create_purchase_order(qty=4)
				batch_id = f"BATCH-{frappe.generate_hash(length=6)}"
				item_code = purchase_order.items[0].item_code
				frappe.db.set_value("Item", item_code, "has_batch_no", 1, update_modified=False)
				frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": item_code}).insert(
					ignore_permissions=True
				)
				asn = make_test_asn(
					purchase_order=purchase_order,
					supplier_invoice_no=f"GP-CREATE-{frappe.generate_hash(length=8)}",
					qty=1,
				)
				asn.lr_no = "LR-44"
				asn.lr_date = today()
				asn.items[0].batch_no = batch_id
				# A unique serial name: production-clone sites carry committed
				# Serial No docs for fixed names, bound to a different batch.
				serial_no = f"SER-{frappe.generate_hash(length=8)}"
				asn.items[0].serial_nos = serial_no
				asn.insert(ignore_permissions=True)
				asn.submit()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-before-create")
				self.assertEqual(frappe.db.get_value("Gate Pass", opened["name"], "docstatus"), 0)
				self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name}), 0)
				frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
				created = create_receipt_from_gate_pass(opened["name"])

		self.assertEqual(created["doctype"], "Purchase Receipt")
		receipt = frappe.get_doc("Purchase Receipt", created["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertEqual(receipt.supplier_delivery_note, asn.supplier_invoice_no)
		self.assertEqual(receipt.lr_no, "LR-44")
		self.assertEqual(receipt.items[0].batch_no, batch_id)
		self.assertEqual(receipt.items[0].serial_no, serial_no)
		self.assertEqual(flt(receipt.items[0].qty), 1)
		self.assertEqual(flt(receipt.items[0].received_qty), 1)
		gate_pass = frappe.get_doc("Gate Pass", opened["name"])
		if frappe.get_meta("Purchase Receipt").has_field("custom_invoice_no"):
			self.assertEqual(receipt.custom_invoice_no, gate_pass.invoice_number)
		if frappe.get_meta("Purchase Receipt").has_field("custom_purchase_receipt_type"):
			self.assertEqual(receipt.custom_purchase_receipt_type, gate_pass.gate_pass_type)
		if frappe.get_meta("Purchase Receipt Item").has_field("custom_gate_pass"):
			self.assertEqual(receipt.items[0].custom_gate_pass, gate_pass.name)
			self.assertTrue(receipt.items[0].custom_gate_pass_item)

		with (
			patch("asn_module.handlers.purchase_receipt.store_scan_code"),
		):
			receipt.submit()
		invoice = create_from_purchase_receipt("Purchase Receipt", receipt.name, {})
		self.assertEqual(invoice["doctype"], "Purchase Invoice")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", invoice["name"], "asn"), asn.name)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", invoice["name"], "docstatus"), 0)

	def test_a_second_create_opens_the_same_purchase_receipt(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-before-second-create")
				frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
				first = create_receipt_from_gate_pass(opened["name"])
				second = create_receipt_from_gate_pass(opened["name"])

		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": 0}), 1)

	def test_create_opens_a_draft_purchase_receipt_already_on_the_notice(self):
		with with_gate_pass_mode(True) as mode:
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-before-existing-receipt")
				frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
				mode.set(False)
				existing = create_gate_pass_from_asn("ASN", asn.name, {})
				created = create_receipt_from_gate_pass(opened["name"])

		self.assertEqual(created["name"], existing["name"])
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name}), 1)

	def test_create_refuses_a_gate_pass_that_is_not_linked_to_an_asn(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-without-asn")
				frappe.db.set_value(
					"Gate Pass", opened["name"], {"asn": "", "docstatus": 1}, update_modified=False
				)
				with self.assertRaises(frappe.ValidationError) as raised:
					create_receipt_from_gate_pass(opened["name"])

		self.assertIn("not linked to an asn", str(raised.exception).lower())

	def test_create_refuses_a_user_without_a_stock_role(self):
		email = ensure_integration_user("asn.accounts.only@asn-module.test", roles=("Accounts User",))
		previous_in_test = frappe.flags.in_test
		try:
			with integration_user_context(email), self.assertRaises(frappe.PermissionError):
				# v15's frappe.only_for skips the role check entirely while
				# in_test is set; v16 checks roles regardless.
				frappe.flags.in_test = False
				create_receipt_from_gate_pass("GP-NO-STOCK")
		finally:
			frappe.flags.in_test = previous_in_test

	def test_create_on_a_submitted_job_gate_pass_opens_a_subcontracting_receipt_linked_to_the_asn(self):
		with with_gate_pass_mode(True):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				_order, asn = self._submitted_job_asn(shipped_qty=1)
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				opened = dispatch(code=code, device_info="job-gate-pass-before-create")
				self.assertEqual(frappe.db.get_value("Gate Pass", opened["name"], "docstatus"), 0)
				self.assertEqual(frappe.db.count("Subcontracting Receipt", {"asn": asn.name}), 0)
				with self.assertRaises(frappe.ValidationError):
					create_receipt_from_gate_pass(opened["name"])
				line_name = frappe.db.get_value("Gate Pass Item Table", {"parent": opened["name"]}, "name")
				frappe.db.set_value("Gate Pass Item Table", line_name, "qty", 2, update_modified=False)
				frappe.db.set_value("Gate Pass", opened["name"], "docstatus", 1, update_modified=False)
				reopened = dispatch(code=code, device_info="job-gate-pass-after-submit")
				self.assertEqual(reopened["name"], opened["name"])
				created = create_receipt_from_gate_pass(opened["name"])

		self.assertEqual(created["doctype"], "Subcontracting Receipt")
		receipt = frappe.get_doc("Subcontracting Receipt", created["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertEqual(flt(receipt.items[0].qty), 2)

	def test_create_after_the_subcontracting_receipt_is_submitted_is_refused(self):
		with with_gate_pass_mode(True):
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				_order, asn = self._submitted_job_asn(shipped_qty=1)
				code = get_or_create_scan_code(ASN_GATE_PASS_SCAN_ACTION, "ASN", asn.name)
				gate_pass_name = dispatch(code=code, device_info="job-gate-pass-receipt")["name"]
				frappe.db.set_value("Gate Pass", gate_pass_name, "docstatus", 1, update_modified=False)
				created = create_receipt_from_gate_pass(gate_pass_name)
			submit_subcontracting_receipt_hooks(frappe.get_doc("Subcontracting Receipt", created["name"]))
			self.assertEqual(frappe.db.get_value("ASN", asn.name, "status"), "Received")

			with (
				integration_user_context(),
				self.assertRaisesRegex(frappe.ValidationError, "Cannot create Subcontracting Receipt"),
			):
				create_receipt_from_gate_pass(gate_pass_name)

		self.assertEqual(frappe.db.count("Subcontracting Receipt", {"asn": asn.name}), 1)

	def test_a_gate_pass_draft_runs_gate_pass_validation(self):
		# The custom Gate Pass DocType has no validate method; create=True adds one.
		controller = type(frappe.new_doc("Gate Pass"))
		original_validate = getattr(controller, "validate", None)

		def validate(doc, *args, **kwargs):
			if doc.doctype != "Gate Pass":
				if original_validate:
					return original_validate(doc, *args, **kwargs)
				return None
			frappe.throw(_("refused by gate pass rules"))

		# Job drafts too: production's Before Save server script must run on them.
		for submitted_asn in (self._submitted_material_asn, self._submitted_job_asn):
			with self.subTest(submitted_asn.__name__):
				with with_gate_pass_mode(True):
					with integration_user_context():
						_order, asn = submitted_asn()
						with (
							patch.object(controller, "validate", validate, create=True),
							self.assertRaises(frappe.ValidationError) as raised,
						):
							create_gate_pass_from_asn("ASN", asn.name, {})

				self.assertIn("refused by gate pass rules", str(raised.exception).lower())

	def test_a_second_create_reopens_the_draft_gate_pass(self):
		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				first = create_gate_pass_from_asn("ASN", asn.name, {})
				second = create_gate_pass_from_asn("ASN", asn.name, {})

		self.assertEqual(second["name"], first["name"])

	def test_scanning_refuses_when_gate_pass_is_not_installed(self):
		real_exists = frappe.db.exists

		def exists(doctype, name=None, *args, **kwargs):
			if doctype == "DocType" and name == "Gate Pass":
				return None
			return real_exists(doctype, name, *args, **kwargs)

		with with_gate_pass_mode(True):
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				with (
					patch("asn_module.handlers.purchase_receipt.frappe.db.exists", side_effect=exists),
					self.assertRaises(frappe.ValidationError) as raised,
				):
					create_gate_pass_from_asn("ASN", asn.name, {})

		self.assertIn("not set up", str(raised.exception).lower())

	def test_gate_pass_setup_adds_a_missing_asn_link_before_scan_code(self):
		meta = SimpleNamespace(get_field=lambda _name: None)
		with (
			patch("asn_module.custom_fields.gate_pass.frappe.db.exists", return_value=True),
			patch("asn_module.custom_fields.gate_pass.frappe.get_meta", return_value=meta),
			patch("asn_module.custom_fields.gate_pass.create_custom_fields") as create_custom_fields,
		):
			setup_gate_pass_fields()

		fields = create_custom_fields.call_args.args[0]["Gate Pass"]
		self.assertEqual(fields[0]["fieldname"], "asn")
		self.assertEqual(fields[0]["options"], "ASN")
		self.assertEqual(fields[1]["insert_after"], "asn")

	def test_gate_pass_setup_rejects_a_native_asn_field_of_the_wrong_type(self):
		meta = SimpleNamespace(get_field=lambda _name: SimpleNamespace(fieldtype="Data", options=None))
		with (
			patch("asn_module.custom_fields.gate_pass.frappe.db.exists", return_value=True),
			patch("asn_module.custom_fields.gate_pass.frappe.get_meta", return_value=meta),
			patch("asn_module.custom_fields.gate_pass.create_custom_fields") as create_custom_fields,
			self.assertRaises(frappe.ValidationError),
		):
			setup_gate_pass_fields()
		create_custom_fields.assert_not_called()

	def test_scan_fails_clearly_when_gate_pass_has_no_asn_field(self):
		meta = SimpleNamespace(has_field=lambda _name: False)
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.db.exists", return_value=True),
			patch("asn_module.handlers.purchase_receipt.frappe.get_meta", return_value=meta),
			self.assertRaises(frappe.ValidationError) as raised,
		):
			_reopen_uncancelled_gate_pass(SimpleNamespace(name="ASN-1"))
		self.assertIn("migrate", str(raised.exception).lower())

	def test_optional_gate_pass_fields_are_left_unset(self):
		gate_pass = frappe.new_doc("Gate Pass")
		_set_if_present(gate_pass, "vehicle_number", None)
		_set_if_present(gate_pass, "not_a_field", "MH12AB1234")
		self.assertFalse(gate_pass.vehicle_number)


class TestReceiptHelpers(FrappeTestCase):
	def test_shipped_qty_skips_a_receipt_line_that_is_not_on_the_notice(self):
		asn = SimpleNamespace(
			items=[
				SimpleNamespace(subcontracting_order_item="", qty=1),
				SimpleNamespace(subcontracting_order_item="FG-1", qty=2),
			]
		)
		receipt = SimpleNamespace(
			items=[
				SimpleNamespace(
					subcontracting_order_item="FG-OTHER", qty=9, received_qty=9, rate=3, amount=27
				),
				SimpleNamespace(subcontracting_order_item="FG-1", qty=9, received_qty=9, rate=4, amount=36),
			]
		)

		_apply_shipped_qty_to_subcontracting_receipt(receipt, asn)

		self.assertEqual(receipt.items[0].qty, 9)
		self.assertEqual(receipt.items[1].qty, 2)
		self.assertEqual(receipt.items[1].received_qty, 2)
		self.assertEqual(receipt.items[1].amount, 8)

	def test_shipped_qty_clears_process_loss_so_the_receipt_line_is_the_shipped_qty(self):
		asn = SimpleNamespace(items=[SimpleNamespace(subcontracting_order_item="FG-1", qty=2)])
		receipt = SimpleNamespace(
			items=[
				SimpleNamespace(
					subcontracting_order_item="FG-1",
					qty=1.5,
					received_qty=1.5,
					rate=4,
					amount=6,
					process_loss_qty=0.5,
				)
			]
		)

		_apply_shipped_qty_to_subcontracting_receipt(receipt, asn)

		self.assertEqual(receipt.items[0].qty, 2)
		self.assertEqual(receipt.items[0].received_qty, 2)
		self.assertEqual(receipt.items[0].process_loss_qty, 0)
		self.assertEqual(receipt.items[0].amount, 8)

	def test_a_material_notice_must_name_one_purchase_order_and_its_lines(self):
		with self.assertRaises(frappe.ValidationError):
			_get_single_purchase_order(
				SimpleNamespace(
					name="ASN-1",
					items=[SimpleNamespace(purchase_order="", purchase_order_item="")],
				)
			)
		with self.assertRaises(frappe.ValidationError):
			_get_single_purchase_order(
				SimpleNamespace(
					name="ASN-1",
					items=[
						SimpleNamespace(purchase_order="PO-1", purchase_order_item="POI-1"),
						SimpleNamespace(purchase_order="PO-2", purchase_order_item="POI-2"),
					],
				)
			)
		with self.assertRaises(frappe.ValidationError):
			_get_single_purchase_order(
				SimpleNamespace(
					name="ASN-1",
					items=[SimpleNamespace(purchase_order="PO-1", purchase_order_item="")],
				)
			)

	def test_stamp_keeps_the_quantity_received_at_the_gate(self):
		pr_item = SimpleNamespace(
			purchase_order_item="POI-1",
			qty=8,
			stock_qty=8,
			conversion_factor=1,
			rate=2,
			batch_no=None,
			serial_no=None,
			idx=1,
		)
		receipt = SimpleNamespace(
			doctype="Purchase Receipt",
			asn=None,
			items=[pr_item],
			supplier=None,
			supplier_name="Kept",
			title=None,
			supplier_delivery_note=None,
			transporter_name=None,
			vehicle_no=None,
			driver_name=None,
			lr_no=None,
			lr_date=None,
			conversion_rate=1,
			asn_items=None,
			get=lambda field: "GP-1" if field == "custom_gate_pass_reference" else None,
		)
		asn = SimpleNamespace(
			name="ASN-1",
			supplier="Sup",
			supplier_name="Sup",
			supplier_invoice_no="INV-1",
			transporter_name=None,
			vehicle_number=None,
			driver_contact=None,
			lr_no="LR-1",
			lr_date=None,
			items=[
				SimpleNamespace(
					name="ASNI-1",
					purchase_order_item="POI-1",
					qty=10,
					batch_no="BATCH",
					serial_nos="SER",
				)
			],
		)
		gate_pass_row = SimpleNamespace(purchase_order_item="POI-1", receive_qty=8)
		gate_pass = SimpleNamespace(get=lambda field: [gate_pass_row] if field == "items" else None)
		with (
			patch("asn_module.handlers.purchase_receipt.frappe.db.exists", return_value=True),
			patch("asn_module.handlers.purchase_receipt.frappe.db.has_column", return_value=True),
			patch("asn_module.handlers.purchase_receipt.frappe.db.get_value", return_value="ASN-1"),
			patch(
				"asn_module.handlers.purchase_receipt.frappe.get_doc",
				side_effect=lambda doctype, _name: gate_pass if doctype == "Gate Pass" else asn,
			),
		):
			stamp_receipt_built_by_gate_pass(receipt)

		self.assertEqual(receipt.asn, "ASN-1")
		self.assertEqual(receipt.supplier_delivery_note, "INV-1")
		self.assertEqual(pr_item.qty, 8)
		self.assertEqual(pr_item.batch_no, "BATCH")
		self.assertEqual(pr_item.serial_no, "SER")

	def test_arriving_qty_is_read_from_the_items_table(self):
		items_field = SimpleNamespace(fieldtype="Table", options="Gate Pass Items")
		gate_pass = SimpleNamespace(
			meta=SimpleNamespace(get_field=lambda name: items_field if name == "items" else None),
			get=lambda name: (
				[SimpleNamespace(subcontracting_order_item="FG-1", qty=3)] if name == "items" else []
			),
		)
		receipt = SimpleNamespace(
			items=[SimpleNamespace(subcontracting_order_item="FG-1", qty=1, received_qty=1, rate=4, amount=4)]
		)
		child_meta = SimpleNamespace(
			fields=[
				SimpleNamespace(fieldname="subcontracting_order_item"),
				SimpleNamespace(fieldname="qty"),
			]
		)
		with patch("asn_module.handlers.purchase_receipt.frappe.get_meta", return_value=child_meta):
			changed = _apply_gate_pass_qty_to_subcontracting_receipt(receipt, gate_pass)

		self.assertTrue(changed)
		self.assertEqual(receipt.items[0].qty, 3)
		self.assertEqual(receipt.items[0].received_qty, 3)
