from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from asn_module.templates.pages.asn import (
	_get_supplier_for_user,
	cancel_portal_asn,
	delete_portal_asn,
	get_context,
	has_website_permission,
)
from asn_module.tests.compat import IntegrationTestCase
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def _test_dates():
	return get_fiscal_year_test_dates()


class TestASNPortalRouting(IntegrationTestCase):
	"""The /asn route must reach this app's portal page, not Frappe's generic list view.

	The ASN DocType has has_web_view, so Frappe turns its doctype-level `route` into a
	website rule. A doctype-level route of "asn" rewrites /asn to the endpoint "ASN",
	which no template file matches on a case-sensitive filesystem -- so Frappe falls
	through to ListPage, which needs read permission on ASN that portal suppliers do not
	have, and every supplier gets 403 Not Permitted.
	"""

	def test_asn_doctype_does_not_claim_the_portal_list_route(self):
		route = frappe.db.get_value("DocType", "ASN", "route")

		self.assertFalse(
			(route or "").strip("/"),
			"ASN's doctype-level route shadows the supplier portal page at /asn. "
			"Per-document routes come from each ASN's own route field and do not need it.",
		)

	def test_asn_route_resolves_to_the_portal_template_not_the_list_view(self):
		from frappe.website.page_renderers.template_page import TemplatePage
		from frappe.website.path_resolver import PathResolver
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		# A real request is required: evaluate_dynamic_routes reads request.environ, and
		# without one the doctype route rules are skipped entirely and this test would
		# pass even while /asn is returning 403 in production.
		original_request = getattr(frappe.local, "request", None)
		frappe.local.request = Request(EnvironBuilder(path="/asn", method="GET").get_environ())
		try:
			_endpoint, renderer = PathResolver("asn").resolve()
		finally:
			frappe.local.request = original_request

		# Exact type, not isinstance: ListPage subclasses TemplatePage, so isinstance
		# passes for the very renderer this test exists to reject.
		self.assertIs(
			type(renderer),
			TemplatePage,
			f"/asn resolved to {type(renderer).__name__}; suppliers need the portal template.",
		)


class TestASNPortalPageAgainstRealDatabase(IntegrationTestCase):
	"""Executes get_context's real queries instead of mocking frappe.get_all.

	Every other test in this file mocks get_all, so none of them can catch a `fields`
	argument this Frappe version's query layer refuses to parse -- the aggregate syntax
	differs between v15 and v16. This class exists to run the query for real.
	"""

	def test_get_context_builds_item_counts_on_this_frappe_version(self):
		context = SimpleNamespace()

		# Only supplier resolution is stubbed; every query below it hits the database.
		# A supplier with no ASNs is enough: the item-count query still runs, and it is
		# the query layer's parsing of `fields` that broke, not the rows it returned.
		with patch(
			"asn_module.templates.pages.asn._get_supplier_for_user",
			return_value="_Test Portal Supplier With No ASNs",
		):
			get_context(context)

		self.assertTrue(context.can_create_asn)
		self.assertEqual(context.asn_list, [])


class TestASNPortalPage(IntegrationTestCase):
	def test_templates_use_website_route_and_gate_desk_create_action(self):
		asn_page = Path(__file__).with_name("asn.html").read_text()
		asn_row = Path(__file__).with_name("asn_row.html").read_text()
		asn_detail = (
			Path(__file__).parents[2] / "asn_module" / "doctype" / "asn" / "templates" / "asn.html"
		).read_text()

		self.assertIn("{% if can_create_asn %}", asn_page)
		self.assertIn('href="/asn_new"', asn_page)
		self.assertIn('href="/{{ asn.route }}"', asn_row)
		self.assertIn("asn-portal-delete-btn", asn_row)
		self.assertNotIn("/app/asn/{{ asn.name }}", asn_row)
		self.assertIn("asn-copy-scan-code-btn", asn_detail)
		self.assertIn("asn_module.qr_engine.generate.scan_image", asn_detail)
		self.assertNotIn("doc.qr_code", asn_detail)
		self.assertNotIn("doc.barcode", asn_detail)

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

	def test_get_supplier_for_user_returns_none_for_administrator(self):
		with patch("asn_module.templates.pages.asn.frappe.db.get_value") as get_value:
			supplier = _get_supplier_for_user("Administrator")

		self.assertIsNone(supplier)
		get_value.assert_not_called()

	def test_has_website_permission_uses_session_user_when_user_not_passed(self):
		doc = SimpleNamespace(supplier="Supp-001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
		):
			self.assertTrue(has_website_permission(doc, "read"))

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
					"route": "asn/asn-0001",
					"supplier_invoice_no": "INV-001",
					"status": "Submitted",
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
					"asn_date": _test_dates()["asn_date"],
					"docstatus": 1,
				}
			)
		]

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.db.has_column", return_value=True),
			patch(
				"asn_module.templates.pages.asn.frappe.get_all",
				side_effect=[
					asn_rows,
					[],
					# One row per ASN Item, which is what the real query now returns.
					[frappe._dict({"parent": "ASN-0001"}), frappe._dict({"parent": "ASN-0001"})],
				],
			) as get_all,
			patch("asn_module.templates.pages.asn.frappe.db.set_value") as set_value,
		):
			get_context(context)

		set_value.assert_not_called()
		self.assertEqual(context.title, "ASN")
		self.assertTrue(context.show_sidebar)
		self.assertTrue(context.can_create_asn)
		self.assertEqual(len(context.asn_list), 1)
		self.assertEqual(context.asn_list[0].route, "asn/asn-0001")
		self.assertEqual(context.asn_list[0].total_items, 2)
		self.assertTrue(context.asn_list[0].can_cancel_portal)
		self.assertFalse(context.asn_list[0].can_delete_portal)
		self.assertEqual(get_all.call_count, 3)
		self.assertIn("route", get_all.call_args_list[0].kwargs["fields"])
		self.assertIn("docstatus", get_all.call_args_list[1].kwargs["fields"])
		self.assertEqual(get_all.call_args_list[2].kwargs["fields"], ["parent"])

	def test_get_context_returns_empty_list_when_user_has_no_supplier(self):
		context = SimpleNamespace()

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="unknown@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value=None),
		):
			get_context(context)

		self.assertEqual(context.asn_list, [])

	def test_get_context_disables_cancel_when_purchase_receipt_exists(self):
		context = SimpleNamespace()
		asn_rows = [
			frappe._dict(
				{
					"name": "ASN-0001",
					"route": "asn/asn-0001",
					"supplier_invoice_no": "INV-001",
					"status": "Submitted",
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
					"asn_date": _test_dates()["asn_date"],
					"docstatus": 1,
				}
			)
		]
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.db.has_column", return_value=True),
			patch(
				"asn_module.templates.pages.asn.frappe.get_all",
				side_effect=[
					asn_rows,
					[frappe._dict({"asn": "ASN-0001", "docstatus": 1})],
					[frappe._dict({"parent": "ASN-0001", "total_items": 1})],
				],
			),
			patch("asn_module.templates.pages.asn.frappe.db.set_value"),
		):
			get_context(context)
		self.assertFalse(context.asn_list[0].can_cancel_portal)
		self.assertFalse(context.asn_list[0].can_delete_portal)

	def test_get_context_enables_delete_for_cancelled_without_pr(self):
		context = SimpleNamespace()
		asn_rows = [
			frappe._dict(
				{
					"name": "ASN-0009",
					"route": "asn/asn-0009",
					"supplier_invoice_no": "INV-009",
					"status": "Cancelled",
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
					"asn_date": _test_dates()["asn_date"],
					"docstatus": 2,
				}
			)
		]
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.db.has_column", return_value=True),
			patch(
				"asn_module.templates.pages.asn.frappe.get_all",
				side_effect=[
					asn_rows,
					[],
					[frappe._dict({"parent": "ASN-0009", "total_items": 1})],
				],
			),
			patch("asn_module.templates.pages.asn.frappe.db.set_value"),
		):
			get_context(context)
		self.assertTrue(context.asn_list[0].can_delete_portal)
		self.assertFalse(context.asn_list[0].can_cancel_portal)

	def test_get_context_allows_delete_when_only_cancelled_purchase_receipt(self):
		"""Cancelled PR rows must not hide Delete on the portal (same as cancel rule)."""
		context = SimpleNamespace()
		asn_rows = [
			frappe._dict(
				{
					"name": "ASN-0008",
					"route": "asn/asn-0008",
					"supplier_invoice_no": "INV-008",
					"status": "Cancelled",
					"expected_delivery_date": _test_dates()["expected_delivery_date"],
					"asn_date": _test_dates()["asn_date"],
					"docstatus": 2,
				}
			)
		]
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.db.has_column", return_value=True),
			patch(
				"asn_module.templates.pages.asn.frappe.get_all",
				side_effect=[
					asn_rows,
					[frappe._dict({"asn": "ASN-0008", "docstatus": 2})],
					[frappe._dict({"parent": "ASN-0008", "total_items": 1})],
				],
			),
			patch("asn_module.templates.pages.asn.frappe.db.set_value"),
		):
			get_context(context)
		self.assertTrue(context.asn_list[0].can_delete_portal)

	def test_cancel_portal_asn_rejects_without_supplier_portal_user(self):
		with (
			patch("asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="x@y.com")),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value=None),
		):
			with self.assertRaises(frappe.PermissionError):
				cancel_portal_asn("ASN-0001")

	def test_cancel_portal_asn_rejects_empty_name(self):
		with self.assertRaises(frappe.ValidationError):
			cancel_portal_asn(" ")

	def test_cancel_portal_asn_rejects_other_supplier(self):
		doc = SimpleNamespace(supplier="Supp-002", docstatus=1, status="Submitted", name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.PermissionError),
		):
			cancel_portal_asn("ASN-0001")

	def test_cancel_portal_asn_rejects_non_submitted_docstatus(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=0, status="Draft", name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.ValidationError),
		):
			cancel_portal_asn("ASN-0001")

	def test_cancel_portal_asn_rejects_wrong_status(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=1, status="Received", name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.ValidationError),
		):
			cancel_portal_asn("ASN-0001")

	def test_cancel_portal_asn_rejects_existing_purchase_receipt(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=1, status="Submitted", name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			patch("asn_module.templates.pages.asn.purchase_receipt_exists_for_asn", return_value=True),
			self.assertRaises(frappe.ValidationError),
		):
			cancel_portal_asn("ASN-0001")

	def test_cancel_portal_asn_calls_cancel_when_eligible(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=1, status="Submitted", name="ASN-0001")
		doc.flags = SimpleNamespace(ignore_permissions=False)
		cancelled: list[bool] = []

		def _cancel():
			cancelled.append(True)

		doc.cancel = _cancel

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			patch("asn_module.templates.pages.asn.purchase_receipt_exists_for_asn", return_value=False),
		):
			out = cancel_portal_asn("ASN-0001")
		self.assertTrue(cancelled)
		self.assertEqual(out.get("redirect"), "/asn")

	def test_delete_portal_asn_rejects_without_supplier_portal_user(self):
		with (
			patch("asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="x@y.com")),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value=None),
		):
			with self.assertRaises(frappe.PermissionError):
				delete_portal_asn("ASN-0001")

	def test_delete_portal_asn_rejects_empty_name(self):
		with self.assertRaises(frappe.ValidationError):
			delete_portal_asn("")

	def test_delete_portal_asn_rejects_other_supplier(self):
		doc = SimpleNamespace(supplier="Supp-002", docstatus=2, name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.PermissionError),
		):
			delete_portal_asn("ASN-0001")

	def test_delete_portal_asn_rejects_non_cancelled_docstatus(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=1, name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			self.assertRaises(frappe.ValidationError),
		):
			delete_portal_asn("ASN-0001")

	def test_delete_portal_asn_rejects_existing_purchase_receipt(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=2, name="ASN-0001")
		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			patch("asn_module.templates.pages.asn.purchase_receipt_exists_for_asn", return_value=True),
			self.assertRaises(frappe.ValidationError),
		):
			delete_portal_asn("ASN-0001")

	def test_delete_portal_asn_calls_delete_when_eligible(self):
		doc = SimpleNamespace(supplier="Supp-001", docstatus=2, name="ASN-0001")
		deleted: list[str] = []

		def _delete_doc(dt, name, **_k):
			deleted.append(f"{dt}:{name}")

		with (
			patch(
				"asn_module.templates.pages.asn.frappe.session", SimpleNamespace(user="supplier@example.com")
			),
			patch("asn_module.templates.pages.asn._get_supplier_for_user", return_value="Supp-001"),
			patch("asn_module.templates.pages.asn.frappe.get_doc", return_value=doc),
			patch("asn_module.templates.pages.asn.purchase_receipt_exists_for_asn", return_value=False),
			patch("asn_module.templates.pages.asn.frappe.delete_doc", side_effect=_delete_doc),
		):
			out = delete_portal_asn("ASN-0001")
		self.assertEqual(deleted, ["ASN:ASN-0001"])
		self.assertEqual(out.get("redirect"), "/asn")

	def test_get_open_purchase_orders_returns_empty_for_empty_supplier(self):
		from asn_module.templates.pages.asn import get_open_purchase_orders_for_supplier

		result = get_open_purchase_orders_for_supplier("")
		self.assertEqual(result, [])

	def test_open_purchase_orders_omit_subcontracted_purchase_orders(self):
		from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
		from asn_module.templates.pages.asn import get_open_purchase_orders_for_supplier

		material = create_purchase_order(qty=1)
		subcontracted = create_purchase_order(supplier=material.supplier, qty=1)
		frappe.db.set_value("Purchase Order", subcontracted.name, "is_subcontracted", 1)
		names = [row.name for row in get_open_purchase_orders_for_supplier(material.supplier)]
		self.assertIn(material.name, names)
		self.assertNotIn(subcontracted.name, names)
