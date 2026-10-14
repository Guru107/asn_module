import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, flt, today

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
	real_asn_attachment_context,
)
from asn_module.handlers.purchase_receipt import create_from_asn
from asn_module.handlers.tests.test_subcontracting import (
	TestSubcontractingHandlers,
	patch_subcontracting_incoming_rate,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions
from asn_module.templates.pages.asn_new_services import create_job_asn_for_supplier
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context
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


class TestJobAsnScan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		register_actions()
		ensure_integration_user()

	def test_scanning_a_job_asn_opens_a_draft_subcontracting_receipt_for_the_shipped_qty(self):
		self.assertEqual(cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode")), 0)
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
		with real_asn_attachment_context():
			asn.submit()

		code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		with integration_user_context(), patch_subcontracting_incoming_rate(5):
			first = dispatch(code=code, device_info="job-asn")
			reopened = create_from_asn("ASN", asn.name, {})
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


def ensure_gate_pass_for_tests() -> None:
	"""Give the scan a Gate Pass to save.

	CI has no Gate Pass. This bench has the gate_entry DocType, which has no
	``gate_pass_type`` and no ``items`` table. Missing fields are custom fields
	on that DocType. The gate_entry controller is left as it is.
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
					},
					{
						"fieldname": "gate_pass_type",
						"fieldtype": "Link",
						"options": "Gate Pass Type",
						"label": "Gate Pass Type",
					},
					{"fieldname": "document_reference", "fieldtype": "Data", "label": "Document Reference"},
					{"fieldname": "reference_number", "fieldtype": "Data", "label": "Reference Number"},
					{"fieldname": "company", "fieldtype": "Link", "options": "Company", "label": "Company"},
					{"fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "label": "Supplier"},
					{"fieldname": "vehicle_number", "fieldtype": "Data", "label": "Vehicle Number"},
					{"fieldname": "invoice_number", "fieldtype": "Data", "label": "Invoice Number"},
					{"fieldname": "invoice_date", "fieldtype": "Date", "label": "Invoice Date"},
					{"fieldname": "asn", "fieldtype": "Link", "options": "ASN", "label": "ASN"},
					{"fieldname": "items", "fieldtype": "Table", "options": "Gate Pass Item", "label": "Items"},
				],
				"permissions": [
					{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
					{"role": "Stock User", "read": 1, "write": 1, "create": 1},
					{"role": "Stock Manager", "read": 1, "write": 1, "create": 1},
				],
			}
		).insert(ignore_permissions=True)
		return

	meta = frappe.get_meta("Gate Pass")
	custom_fields = []
	if not meta.has_field("gate_pass_type"):
		custom_fields.append(
			{
				"fieldname": "gate_pass_type",
				"fieldtype": "Link",
				"options": "Gate Pass Type",
				"label": "Gate Pass Type",
				"insert_after": "entry_type",
			}
		)
	if not meta.has_field("invoice_number"):
		custom_fields.append(
			{
				"fieldname": "invoice_number",
				"fieldtype": "Data",
				"label": "Invoice Number",
				"insert_after": "supplier",
			}
		)
	if not meta.has_field("invoice_date"):
		custom_fields.append(
			{
				"fieldname": "invoice_date",
				"fieldtype": "Date",
				"label": "Invoice Date",
				"insert_after": "invoice_number",
			}
		)
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
	if not meta.has_field("items"):
		custom_fields.append(
			{
				"fieldname": "items",
				"fieldtype": "Table",
				"options": "Gate Pass Item",
				"label": "Items",
				"insert_after": "supplier",
			}
		)
	if custom_fields:
		create_custom_fields({"Gate Pass": custom_fields})
		frappe.clear_cache(doctype="Gate Pass")


class TestMaterialGatePassScan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		register_actions()
		ensure_integration_user()
		ensure_gate_pass_for_tests()

	def test_scanning_a_material_asn_with_gate_pass_mode_on_opens_a_draft_gate_pass(self):
		previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 1)
		try:
			with integration_user_context():
				purchase_order = create_purchase_order(qty=4)
				shipped_qty = 2
				asn = make_test_asn(
					purchase_order=purchase_order,
					supplier_invoice_no=f"GP-ON-{frappe.generate_hash(length=8)}",
					qty=shipped_qty,
				)
				asn.insert(ignore_permissions=True)
				with real_asn_attachment_context():
					asn.submit()
				code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
				result = dispatch(code=code, device_info="gate-pass-on")
		finally:
			frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)

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
		with real_asn_attachment_context():
			asn.submit()
		return purchase_order, asn

	def test_a_later_scan_opens_the_same_gate_pass(self):
		previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 1)
		try:
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
				first = dispatch(code=code, device_info="gate-pass-on")
				second = dispatch(code=code, device_info="gate-pass-on-again")
		finally:
			frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)

		self.assertEqual(first["doctype"], "Gate Pass")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_cancelled_gate_pass_does_not_block_a_new_draft(self):
		previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 1)
		try:
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
				first = dispatch(code=code, device_info="gate-pass-on")
				frappe.db.set_value("Gate Pass", first["name"], "docstatus", 2, update_modified=False)
				second = dispatch(code=code, device_info="gate-pass-after-cancel")
		finally:
			frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)

		self.assertEqual(second["doctype"], "Gate Pass")
		self.assertNotEqual(second["name"], first["name"])
		self.assertEqual(frappe.db.get_value("Gate Pass", second["name"], "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Gate Pass", second["name"], "asn"), asn.name)
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 1)

	def test_a_draft_purchase_receipt_wins_over_a_gate_pass(self):
		previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 0)
		try:
			with integration_user_context():
				_purchase_order, asn = self._submitted_material_asn()
				receipt = create_from_asn("ASN", asn.name, {})
				frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 1)
				code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
				opened = dispatch(code=code, device_info="gate-pass-on-existing-receipt")
		finally:
			frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)

		self.assertEqual(opened["doctype"], "Purchase Receipt")
		self.assertEqual(opened["name"], receipt["name"])
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name, "docstatus": 0}), 0)

	def test_a_job_asn_still_opens_a_subcontracting_receipt_when_gate_pass_mode_is_on(self):
		previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", 1)
		try:
			subcontracting_order = TestSubcontractingHandlers()._make_integration_subcontracting_order()
			finished_good = subcontracting_order.items[0]
			asn = create_job_asn_for_supplier(
				supplier=subcontracting_order.supplier,
				subcontracting_order=subcontracting_order.name,
				header={
					"supplier_invoice_no": f"JOB-GP-{frappe.generate_hash(length=8)}",
					"supplier_invoice_date": today(),
					"vehicle_number": "MH12AB1234",
					"supplier_invoice_amount": finished_good.rate,
				},
				lines=[{"subcontracting_order_item": finished_good.name, "qty": 1}],
			)
			with real_asn_attachment_context():
				asn.submit()
			code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
			with integration_user_context(), patch_subcontracting_incoming_rate(5):
				result = dispatch(code=code, device_info="job-asn-gate-pass-on")
		finally:
			frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)

		self.assertEqual(result["doctype"], "Subcontracting Receipt")
		self.assertEqual(frappe.db.count("Gate Pass", {"asn": asn.name}), 0)
