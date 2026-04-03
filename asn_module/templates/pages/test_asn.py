from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages.asn import _get_supplier_for_user, get_context, has_website_permission


class TestASNPortalPage(FrappeTestCase):
	def test_templates_use_website_route_and_gate_desk_create_action(self):
		asn_page = Path(__file__).with_name("asn.html").read_text()
		asn_row = Path(__file__).with_name("asn_row.html").read_text()

		self.assertIn("{% if can_create_asn %}", asn_page)
		self.assertIn('href="/app/asn/new"', asn_page)
		self.assertIn('href="/{{ asn.route }}"', asn_row)
		self.assertNotIn("/app/asn/{{ asn.name }}", asn_row)

	def test_get_supplier_for_user_returns_portal_supplier(self):
		with patch(
			"asn_module.templates.pages.asn.frappe.db.get_value", return_value="Supp-001"
		) as get_value:
			supplier = _get_supplier_for_user("supplier@example.com")

		self.assertEqual(supplier, "Supp-001")
		get_value.assert_called_once_with(
			"Portal User",
			{"user": "supplier@example.com", "parenttype": "Supplier"},
			"parent",
		)

	def test_has_website_permission_allows_matching_supplier(self):
		doc = SimpleNamespace(supplier="Supp-001")

		with patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"):
			self.assertTrue(has_website_permission(doc, "read", user="supplier@example.com"))

	def test_has_website_permission_allows_administrator(self):
		doc = SimpleNamespace(supplier="Supp-002")

		self.assertTrue(has_website_permission(doc, "read", user="Administrator"))

	def test_has_website_permission_rejects_other_supplier(self):
		doc = SimpleNamespace(supplier="Supp-002")

		with patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"):
			self.assertFalse(has_website_permission(doc, "read", user="supplier@example.com"))

	def test_get_context_populates_supplier_asn_list(self):
		context = SimpleNamespace()
		asn_rows = [
			frappe._dict(
				{
					"name": "ASN-0001",
					"route": None,
					"supplier_invoice_no": "INV-001",
					"status": "Submitted",
					"expected_delivery_date": "2026-04-05",
					"asn_date": "2026-04-02",
				}
			)
		]

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn.frappe.get_all",
				side_effect=[
					asn_rows,
					[frappe._dict({"parent": "ASN-0001", "total_items": 2})],
				],
			) as get_all,
			patch("asn_module.templates.pages.asn.frappe.db.set_value") as set_value,
			patch("asn_module.templates.pages.asn.frappe.has_permission", return_value=False),
		):
			get_context(context)

		self.assertEqual(context.title, "ASN")
		self.assertTrue(context.show_sidebar)
		self.assertFalse(context.can_create_asn)
		self.assertEqual(len(context.asn_list), 1)
		self.assertEqual(context.asn_list[0].route, "asn/asn-0001")
		self.assertEqual(context.asn_list[0].total_items, 2)
		self.assertEqual(get_all.call_count, 2)
		self.assertIn("route", get_all.call_args_list[0].kwargs["fields"])
		set_value.assert_called_once_with("ASN", "ASN-0001", "route", "asn/asn-0001", update_modified=False)

	def test_get_context_returns_empty_list_when_user_has_no_supplier(self):
		context = SimpleNamespace()

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="unknown@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value=None),
			patch("asn_module.templates.pages.asn.frappe.has_permission", return_value=False),
		):
			get_context(context)

		self.assertEqual(context.asn_list, [])
