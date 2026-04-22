import frappe
from frappe.tests.utils import FrappeTestCase


class TestQRActionDefinition(FrappeTestCase):
	def make_action_definition(
		self,
		*,
		action_key: str = "create_purchase_receipt",
		handler_method: str = "asn_module.handlers.purchase_receipt.create_from_asn",
		source_doctype: str = "ASN",
		allowed_roles: str = "Stock User,Stock Manager",
		is_active: int = 1,
	):
		return frappe.get_doc(
			{
				"doctype": "QR Action Definition",
				"action_key": action_key,
				"handler_method": handler_method,
				"source_doctype": source_doctype,
				"allowed_roles": allowed_roles,
				"is_active": is_active,
			}
		).insert(ignore_permissions=True)

	def test_action_key_unique(self):
		action_key = f"test_unique_action_{frappe.generate_hash(length=8)}"
		self.make_action_definition(action_key=action_key)

		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_action_definition(action_key=action_key)
