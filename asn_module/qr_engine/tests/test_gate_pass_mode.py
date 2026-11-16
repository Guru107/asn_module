import frappe
from frappe.utils import cint

from asn_module.asn_module.doctype.asn.test_asn import (
	create_purchase_order,
	make_test_asn,
)
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.tests.compat import IntegrationTestCase
from asn_module.tests.integration.fixtures import (
	ensure_integration_user,
	integration_user_context,
	pin_gate_pass_mode_for_tests,
)
from asn_module.utils.test_setup import before_tests


class TestGatePassMode(IntegrationTestCase):
	def test_new_site_has_gate_pass_mode_off_and_not_on_the_asn(self):
		self.assertTrue(frappe.db.exists("DocType", "ASN Settings"))
		settings_meta = frappe.get_meta("ASN Settings")
		self.assertEqual(settings_meta.issingle, 1)
		field = settings_meta.get_field("gate_pass_mode")
		self.assertIsNotNone(field)
		self.assertEqual(cint(field.default), 0)

		settings = frappe.new_doc("ASN Settings")
		self.assertEqual(cint(settings.gate_pass_mode), 0)

		self.assertFalse(frappe.get_meta("ASN").has_field("gate_pass_mode"))
		self.assertFalse(frappe.db.has_column("ASN", "gate_pass_mode"))


class TestMaterialAsnScanWhenGatePassModeIsOff(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		ensure_integration_user()
		# This class scans with the mode OFF; configured sites run it ON.
		pin_gate_pass_mode_for_tests(cls)

	def test_scanning_a_material_asn_twice_opens_the_same_draft_purchase_receipt(self):
		with integration_user_context():
			purchase_order = create_purchase_order(qty=2)
			asn = make_test_asn(
				purchase_order=purchase_order,
				supplier_invoice_no=f"GP-OFF-{frappe.generate_hash(length=8)}",
				qty=2,
			)
			asn.insert(ignore_permissions=True)
			asn.submit()
			self.assertEqual({row.purchase_order for row in asn.items}, {purchase_order.name})

			code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
			first = dispatch(code=code, device_info="gate-pass-off")
			second = dispatch(code=code, device_info="gate-pass-off-again")

		self.assertEqual(first["doctype"], "Purchase Receipt")
		self.assertEqual(second["name"], first["name"])
		receipt = frappe.get_doc("Purchase Receipt", first["name"])
		self.assertEqual(receipt.docstatus, 0)
		self.assertEqual(receipt.asn, asn.name)
		self.assertEqual(frappe.db.count("Purchase Receipt", {"asn": asn.name, "docstatus": 0}), 1)
