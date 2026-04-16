from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def fiscal_year_test_dates() -> dict[str, str]:
	"""Compatibility shim for handler tests.

	Canonical FY date logic lives in ``asn_module.tests.financial_year_dates``.
	"""
	dates = get_fiscal_year_test_dates()
	return {
		"transaction_date": dates["transaction_date"],
		"schedule_date": dates["schedule_date"],
		"item_schedule_date": dates["item_schedule_date"],
		"lr_date": dates["lr_date"],
	}
