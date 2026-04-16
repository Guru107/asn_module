from __future__ import annotations

from functools import lru_cache

import frappe
from frappe.utils import add_days, today


@lru_cache(maxsize=1)
def get_fiscal_year_test_dates() -> dict[str, str]:
	"""Return stable test dates that always fall within a single enabled Fiscal Year."""
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
	return {
		"asn_date": asn_date,
		"supplier_invoice_date": invoice_date,
		"expected_delivery_date": expected_delivery_date,
		"lr_date": invoice_date,
		"token_created_at": f"{asn_date} 13:32:44.604410",
	}
