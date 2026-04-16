from __future__ import annotations

import frappe
from frappe.utils import add_days, today


def get_fiscal_year_test_dates() -> dict[str, str]:
	"""Return stable test dates that always fall within a single enabled Fiscal Year."""
	cached = getattr(frappe.local, "_fiscal_year_test_dates", None)
	if cached is not None:
		return cached

	fiscal_year = frappe.db.get_value(
		"Fiscal Year",
		{
			"year_start_date": ["<=", today()],
			"year_end_date": [">=", today()],
			"disabled": 0,
		},
		["year_start_date", "year_end_date"],
		as_dict=True,
	)
	if not fiscal_year:
		fiscal_year = frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			["year_start_date", "year_end_date"],
			as_dict=True,
			order_by="year_start_date asc",
		)
	if not fiscal_year:
		frappe.throw("No enabled Fiscal Year found for tests")

	asn_date = str(fiscal_year.year_start_date)
	invoice_date = str(add_days(asn_date, 3))
	expected_delivery_date = str(add_days(asn_date, 4))
	schedule_date = str(add_days(asn_date, 1))
	result = {
		# Canonical baseline keys used by handlers and portal/template tests.
		"transaction_date": asn_date,
		"schedule_date": schedule_date,
		"item_schedule_date": schedule_date,
		"asn_date": asn_date,
		"supplier_invoice_date": invoice_date,
		"expected_delivery_date": expected_delivery_date,
		"lr_date": invoice_date,
		"token_created_at": f"{asn_date} 13:32:44.604410",
	}
	frappe.local._fiscal_year_test_dates = result
	return result
