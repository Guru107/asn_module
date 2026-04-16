import frappe
from frappe.utils import add_days, nowdate


def fiscal_year_test_dates() -> dict[str, str]:
	current = nowdate()
	fy = frappe.db.get_value(
		"Fiscal Year",
		{
			"disabled": 0,
			"year_start_date": ("<=", current),
			"year_end_date": (">=", current),
		},
		["year_start_date", "year_end_date"],
		as_dict=True,
	)
	if not fy:
		fy = frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			["year_start_date", "year_end_date"],
			as_dict=True,
			order_by="year_start_date asc",
		)
	base = str(fy.year_start_date) if fy else current
	return {
		"transaction_date": base,
		"schedule_date": add_days(base, 1),
		"item_schedule_date": add_days(base, 1),
		"lr_date": add_days(base, 5),
	}

