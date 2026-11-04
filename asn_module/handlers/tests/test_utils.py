from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.handlers.utils import (
	apply_site_document_requirements,
	fill_custom_fiscal_year,
	fiscal_year_for_date,
)


def _doc_with_fiscal_year_field(reqd: int = 1, **values) -> frappe._dict:
	"""A document stub whose meta carries a site-style ``custom_fiscal_year`` field."""
	doc = frappe._dict(
		doctype="Subcontracting Receipt",
		meta=SimpleNamespace(
			get_field=lambda fieldname: (
				SimpleNamespace(reqd=reqd) if fieldname == "custom_fiscal_year" else None
			)
		),
	)
	doc.update(values)
	return doc


class TestFillCustomFiscalYear(FrappeTestCase):
	def test_fills_a_mandatory_field_from_the_posting_date(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19")

		with patch(
			"asn_module.handlers.utils.fiscal_year_for_date", return_value="_Test FY 2026-27"
		) as lookup:
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "_Test FY 2026-27")
		lookup.assert_called_once_with("2026-10-19", company=None)

	def test_falls_back_to_the_transaction_date(self):
		doc = _doc_with_fiscal_year_field(transaction_date="2026-04-05")

		with patch(
			"asn_module.handlers.utils.fiscal_year_for_date", return_value="_Test FY 2026-27"
		) as lookup:
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "_Test FY 2026-27")
		lookup.assert_called_once_with("2026-04-05", company=None)

	def test_leaves_a_doctype_without_the_field_alone(self):
		doc = _doc_with_fiscal_year_field(reqd=0, posting_date="2026-10-19")

		with patch(
			"asn_module.handlers.utils.fiscal_year_for_date", side_effect=AssertionError("must not query")
		):
			fill_custom_fiscal_year(doc)

		self.assertNotIn("custom_fiscal_year", doc)

	def test_keeps_a_value_that_names_a_fiscal_year_the_site_has(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19", custom_fiscal_year="FY 2025-26")

		def fake_exists(doctype, name=None, *args, **kwargs):
			return name == "FY 2025-26"

		with (
			patch.object(frappe.db, "exists", side_effect=fake_exists),
			patch(
				"asn_module.handlers.utils.fiscal_year_for_date", side_effect=AssertionError("must not query")
			),
		):
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "FY 2025-26")

	def test_replaces_a_rollover_default_that_names_a_missing_fiscal_year(self):
		doc = _doc_with_fiscal_year_field(posting_date="2026-10-19", custom_fiscal_year="26-27")

		with (
			patch.object(frappe.db, "exists", return_value=None),
			patch("asn_module.handlers.utils.fiscal_year_for_date", return_value="2026-2027"),
		):
			fill_custom_fiscal_year(doc)

		self.assertEqual(doc.custom_fiscal_year, "2026-2027")

	def test_leaves_the_field_unset_when_no_fiscal_year_covers_the_date(self):
		doc = _doc_with_fiscal_year_field(posting_date="2031-10-19")

		with patch("asn_module.handlers.utils.fiscal_year_for_date", return_value=None):
			fill_custom_fiscal_year(doc)

		self.assertNotIn("custom_fiscal_year", doc)


def _doc_with_taxes_field(reqd: int = 1, **values) -> frappe._dict:
	"""A document stub whose meta carries a site-style mandatory ``taxes`` table."""
	doc = frappe._dict(
		doctype="Purchase Receipt",
		meta=SimpleNamespace(
			get_field=lambda fieldname: SimpleNamespace(reqd=reqd) if fieldname == "taxes" else None
		),
		items=[],
	)
	doc.taxes = []
	doc.append = lambda fieldname, row: doc[fieldname].append(row)
	doc.update(values)
	return doc


class TestApplySiteDocumentRequirements(FrappeTestCase):
	def test_refuses_to_guess_between_several_purchase_orders(self):
		doc = _doc_with_taxes_field(items=[{"purchase_order": "PO-1"}, {"purchase_order": "PO-2"}])

		with (
			patch.object(frappe, "get_doc", side_effect=AssertionError("must not load")),
			self.assertRaises(frappe.ValidationError) as context,
		):
			apply_site_document_requirements(doc)

		self.assertIn("PO-1", str(context.exception))
		self.assertIn("PO-2", str(context.exception))

	def test_leaves_existing_taxes_alone(self):
		doc = _doc_with_taxes_field(
			items=[{"item_code": "X", "purchase_order": "PO-1"}],
			taxes=[{"description": "kept"}],
		)

		with patch.object(frappe, "get_doc", side_effect=AssertionError("must not load")):
			apply_site_document_requirements(doc)

		self.assertEqual(doc.taxes, [{"description": "kept"}])

	def test_no_op_when_the_site_does_not_require_taxes(self):
		doc = _doc_with_taxes_field(reqd=0, items=[{"purchase_order": "PO-1"}])

		with patch.object(frappe, "get_doc", side_effect=AssertionError("must not load")):
			apply_site_document_requirements(doc)

		self.assertEqual(doc.taxes, [])

	def test_no_op_without_a_purchase_order_link(self):
		doc = _doc_with_taxes_field(items=[{"item_code": "X"}])

		with patch.object(frappe, "get_doc", side_effect=AssertionError("must not load")):
			apply_site_document_requirements(doc)

		self.assertEqual(doc.taxes, [])


class TestFiscalYearForDate(FrappeTestCase):
	def test_picks_the_latest_start_date_when_years_overlap(self):
		with patch.object(
			frappe,
			"get_all",
			return_value=[{"name": "FY New"}, {"name": "FY Old"}],
		) as get_all:
			result = fiscal_year_for_date("2026-06-01")

		self.assertEqual(result, "FY New")
		get_all.assert_called_once()
		self.assertIn("year_start_date desc", get_all.call_args.kwargs.get("order_by", ""))

	def test_returns_none_when_no_fiscal_year_covers_the_date(self):
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(fiscal_year_for_date("2031-01-01"))

	def test_returns_candidate_when_company_table_missing(self):
		with (
			patch.object(frappe, "get_all", return_value=[{"name": "FY-Only"}]),
			patch.object(frappe.db, "table_exists", return_value=False),
		):
			self.assertEqual(fiscal_year_for_date("2026-06-01", company="Any Co"), "FY-Only")

	def test_returns_none_when_company_not_linked_to_any_candidate(self):
		with (
			patch.object(frappe, "get_all", side_effect=[[{"name": "FY-A"}], ["Other Co"]]),
			patch.object(frappe.db, "table_exists", return_value=True),
		):
			self.assertIsNone(fiscal_year_for_date("2026-06-01", company="Test Company"))

	def test_scopes_to_company_when_fiscal_year_company_exists(self):
		with (
			patch.object(frappe.db, "table_exists", return_value=True),
			patch.object(
				frappe,
				"get_all",
				side_effect=[
					[{"name": "FY-A"}, {"name": "FY-B"}],
					["Other Co"],
					["Test Company"],
				],
			),
		):
			result = fiscal_year_for_date("2026-06-01", company="Test Company")

		self.assertEqual(result, "FY-B")
