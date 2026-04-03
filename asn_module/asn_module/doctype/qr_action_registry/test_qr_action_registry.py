import frappe
from frappe.tests.utils import FrappeTestCase


class TestQRActionRegistry(FrappeTestCase):
	def _registry_with_action(self, allowed_roles="System Manager, Stock User"):
		return frappe.get_doc(
			{
				"doctype": "QR Action Registry",
				"actions": [
					{
						"doctype": "QR Action Registry Item",
						"action_key": "create_purchase_receipt",
						"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
						"source_doctype": "ASN",
						"allowed_roles": allowed_roles,
					}
				],
			}
		)

	def test_get_action_returns_registered_action(self):
		registry = self._registry_with_action()

		action = registry.get_action("create_purchase_receipt")

		self.assertEqual(action["handler_method"], "asn_module.handlers.purchase_receipt.create_from_asn")
		self.assertEqual(action["source_doctype"], "ASN")
		self.assertEqual(action["allowed_roles"], ["System Manager", "Stock User"])

	def test_get_action_returns_none_for_unknown_action(self):
		registry = self._registry_with_action()

		self.assertIsNone(registry.get_action("unknown_action"))

	def test_get_action_trims_allowed_roles(self):
		registry = self._registry_with_action(" System Manager,  Stock User ,")

		action = registry.get_action("create_purchase_receipt")

		self.assertEqual(action["allowed_roles"], ["System Manager", "Stock User"])

	def test_save_rejects_invalid_allowed_role_names(self):
		registry = self._registry_with_action("System Manager, Not A Role")

		with self.assertRaises(frappe.ValidationError):
			registry.save(ignore_permissions=True)

	def test_save_rejects_empty_allowed_roles_after_trimming(self):
		registry = self._registry_with_action(" , ")

		with self.assertRaises(frappe.ValidationError):
			registry.save(ignore_permissions=True)
