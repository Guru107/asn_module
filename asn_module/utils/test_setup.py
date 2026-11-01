from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

import frappe
from frappe.utils import cint

from asn_module.stock_cap.models import Breach

TEST_COMPANY_NAME = "_Test Company"
TEST_COMPANY_ABBR = "_TC"


def _get_erpnext_before_tests() -> Callable[[], None] | None:
	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		return None

	before_tests = getattr(erpnext_setup_utils, "before_tests", None)
	return before_tests if callable(before_tests) else None


def _bootstrap_erpnext_defaults_without_hook() -> None:
	if not frappe.db.exists("Company", None):
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
		from frappe.utils import now_datetime

		current_year = now_datetime().year
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": TEST_COMPANY_NAME,
				"timezone": "Asia/Kolkata",
				"company_abbr": TEST_COMPANY_ABBR,
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{current_year}-04-01",
				"fy_end_date": f"{current_year + 1}-03-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@asn-module.local",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		erpnext_setup_utils = None

	for fn_name in ("set_defaults_for_tests",):
		fn = getattr(erpnext_setup_utils, fn_name, None) if erpnext_setup_utils else None
		if callable(fn):
			fn()

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - test bootstrap must persist baseline fixtures


def _ensure_company_defaults() -> None:
	company = TEST_COMPANY_NAME if frappe.db.exists("Company", TEST_COMPANY_NAME) else None
	if not company:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		return

	frappe.db.set_single_value("Global Defaults", "default_company", company)
	frappe.defaults.set_user_default("company", company)


def before_tests() -> None:
	"""Ensure a deterministic ERPNext company baseline exists for ASN tests."""
	# v15 test discovery auto-creates test records for every linked doctype of
	# each doctype test file; on multi-app dev sites that machinery needs
	# cross-app test accounts that do not exist (LinkValidationError). ASN tests
	# build their own fixtures, so skip it like india_compliance does.
	frappe.flags.skip_test_records = True

	if not frappe.db.exists("Company", None) or not frappe.db.exists("Cost Center", None):
		if erpnext_before_tests := _get_erpnext_before_tests():
			erpnext_before_tests()
		else:
			_bootstrap_erpnext_defaults_without_hook()

	_ensure_company_defaults()
	ensure_branch_dimension()


def ensure_branch_dimension() -> None:
	"""Make `Purchase Order.branch` and `Purchase Receipt.branch` exist.

	Those columns are not ours: ERPNext's Branch Accounting Dimension creates them as
	custom fields on every transaction doctype. Production has the dimension configured,
	and so do the dev benches, but a freshly-built CI site does not -- which is why the
	stock cap's branch tests passed locally for the whole build and only failed in CI.

	Fails open: a site without the Accounting Dimension doctype simply keeps no branch
	column, which is exactly the configuration the stock cap already skips.
	"""
	if not frappe.db.table_exists("Accounting Dimension"):
		return
	if frappe.db.exists("Accounting Dimension", {"document_type": "Branch"}):
		return
	if not frappe.db.exists("DocType", "Branch"):
		return

	dimension = frappe.get_doc({"doctype": "Accounting Dimension", "document_type": "Branch"})
	dimension.insert(ignore_permissions=True)

	# ERPNext only builds the per-doctype custom fields inline when frappe.in_test is set;
	# otherwise it enqueues them, and a CI run has no worker to pick that up. Build them
	# directly if the column we actually need did not appear.
	if not frappe.db.has_column("Purchase Order", "branch"):
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			make_dimension_in_accounting_doctypes,
		)

		make_dimension_in_accounting_doctypes(doc=dimension)

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - test bootstrap must persist baseline fixtures


def disable_hsn_validation() -> None:
	"""Disable india_compliance's HSN/SAC validation for the current test class.

	Fresh Items created via ``build_purchase_order_with_mandatory_fields()`` (or by hand)
	have no HSN/SAC code. india_compliance's ``Item.validate`` hook rejects that whenever
	the test company's country is India (as ``before_tests()`` sets it up here), which has
	nothing to do with whatever stock-cap behaviour is actually under test. ``--lightmode``
	skips the app-level ``before_tests`` hooks that would otherwise disable this, so
	disable it directly here.

	This bench's ``FrappeTestCase`` only rolls back at class teardown, not per test (see
	``frappe.deprecation_dumpster.FrappeTestCase.setUpClass``). Call this once from
	``setUpClass`` and rely on that class-level rollback to restore the setting -- do not
	attempt to restore it yourself, or you will re-enable HSN validation partway through a
	test class that still needs it disabled.
	"""
	if frappe.db.exists("DocType", "GST Settings"):
		frappe.db.set_single_value("GST Settings", "validate_hsn_code", 0)


def apply_purchase_order_site_requirements(po, *, tax_description: str):
	"""Fill Purchase Order fields this site marks mandatory, and only those.

	``custom_order_type`` and a ``taxes`` row are mandatory here because of Property
	Setters and Custom Fields imported from production. A site without those
	customisations leaves the document unchanged.
	"""
	order_type_field = po.meta.get_field("custom_order_type")
	if order_type_field and order_type_field.reqd and not po.get("custom_order_type"):
		po.custom_order_type = "Material"

	taxes_field = po.meta.get_field("taxes")
	if taxes_field and taxes_field.reqd and not po.get("taxes"):
		tax_account = frappe.db.get_value("Account", {"company": po.company, "is_group": 0}, "name")
		if tax_account:
			po.append(
				"taxes",
				{
					"category": "Total",
					"add_deduct_tax": "Add",
					"charge_type": "Actual",
					"account_head": tax_account,
					"description": tax_description,
					"tax_amount": 0,
				},
			)
	return po


def build_purchase_order_with_mandatory_fields(
	create_purchase_order_fn, *, tax_description, do_not_submit=False, **kwargs
):
	"""Build a real Purchase Order fixture that satisfies this bench's mandatory fields.

	``create_purchase_order_fn`` is passed in rather than imported here so callers that
	need to route through a locally captured or ``unittest.mock.patch(..., side_effect=)``
	reference -- e.g. to transparently patch a module-global ``create_purchase_order`` --
	can do so without this helper importing ``test_asn`` (and risking an import cycle).

	:param tax_description: Description for the synthetic tax row, when one is needed.
		Callers should use a description that identifies which test suite created it.
	:param do_not_submit: When ``True``, insert but do not submit the Purchase Order.
	"""
	po = create_purchase_order_fn(do_not_save=True, **kwargs)
	apply_purchase_order_site_requirements(po, tax_description=tax_description)
	po.insert(ignore_permissions=True)
	if not do_not_submit:
		po.submit()
	return po


def resolve_test_company() -> str:
	company = TEST_COMPANY_NAME if frappe.db.exists("Company", TEST_COMPANY_NAME) else None
	return (
		company
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	)


def pin_gate_pass_mode_for_tests(cls, value: int = 0) -> None:
	"""Pin ``ASN Settings.gate_pass_mode`` for a test class, then restore the site's value.

	Receipt-opening scans and handlers assume the fresh-site default (off);
	configured production-clone sites run it ON. ``dispatch`` commits
	mid-test, so the restore commits too -- the site keeps its own setting
	after the run.
	"""
	previous = cint(frappe.db.get_single_value("ASN Settings", "gate_pass_mode"))
	frappe.db.set_single_value("ASN Settings", "gate_pass_mode", value)

	def restore() -> None:
		frappe.db.set_single_value("ASN Settings", "gate_pass_mode", previous)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - outlive dispatch's mid-test commit

	cls.addClassCleanup(restore)


def reset_test_item_stock_flags(item_code: str) -> None:
	"""Clear serial/batch flags a previous run or site import left on a test Item.

	``frappe.db.set_value`` bypasses Item validation on purpose (the flag has
	historical stock-ledger rows behind it) and invalidates the document cache
	itself; a broader ``frappe.clear_cache(doctype=...)`` here would bump the
	global metadata version mid-test and break meta-cold tests.
	"""
	frappe.db.set_value(
		"Item",
		item_code,
		{"has_serial_no": 0, "has_batch_no": 0},
		update_modified=False,
	)


def apply_item_site_requirements(item):
	"""Fill Item fields this site marks mandatory, and only those.

	Production-clone sites make ``Item.gst_hsn_code`` mandatory (Property
	Setter) and mark ``item_tax_template`` mandatory on purchase rows, which
	mapped PO->PR rows only carry when the Item has an Item Tax row. A site
	without those customisations leaves the document unchanged.
	"""
	hsn_field = item.meta.get_field("gst_hsn_code")
	if hsn_field and hsn_field.reqd and not item.get("gst_hsn_code"):
		if hsn_code := frappe.db.get_value("GST HSN Code", {}, "name"):
			item.gst_hsn_code = hsn_code

	pr_item_template = frappe.get_meta("Purchase Receipt Item").get_field("item_tax_template")
	if pr_item_template and pr_item_template.reqd and not item.get("taxes"):
		template = frappe.db.get_value("Item Tax Template", {"company": resolve_test_company()}, "name")
		if template:
			item.append("taxes", {"item_tax_template": template})
	return item


def apply_receipt_site_requirements(receipt):
	"""Fill Purchase Receipt fields this site marks mandatory, and only those.

	``custom_fiscal_year`` (Custom Field, reqd) carries a stale default after a
	fiscal-year rollover on production-clone sites, and ``taxes`` is mandatory
	via Property Setter. A site without those customisations leaves the
	document unchanged.
	"""
	from asn_module.handlers.utils import fill_custom_fiscal_year, fill_mandatory_taxes

	fill_custom_fiscal_year(receipt)
	fill_mandatory_taxes(receipt, description="Test Zero Tax")
	return receipt


def message_log_text() -> str:
	"""Flatten Frappe's message log the way a save warning and a submit block are asserted."""
	return " ".join(str(entry) for entry in frappe.local.message_log or [])


def make_test_breach(
	*,
	branch: str = "Mumbai",
	item_code: str = "WIDGET",
	row_idxs: tuple[int, ...] = (1,),
	on_hand: float = 95.0,
	in_transit: float = 0.0,
	incoming: float = 20.0,
	cap: float = 100.0,
) -> Breach:
	"""Build a real ``Breach`` for tests that stub a breach-producing function's return value.

	Three call sites (the ASN controller, the Purchase Receipt handler, and the supplier
	portal's bulk upload path) each hand-rolled an identical ``SimpleNamespace`` standing in
	for a ``Breach``, and all three had drifted: none of them set ``baseline``, a field
	``models.Breach`` gained when a float-precision bug in ``allowed_qty`` was fixed. A
	``SimpleNamespace`` cannot catch that kind of drift -- it accepts whatever attributes are
	handed to it, dataclass or no. A real ``Breach`` can: construction itself fails the
	moment a field is renamed, added, or removed, so this fixture cannot go stale the way the
	three copies it replaces did.

	``baseline`` and ``projected`` are derived the same way ``evaluate()`` derives them
	(``baseline = on_hand + in_transit``, since none of the current call sites need a
	nonzero ``consumed`` contribution; ``projected = baseline + incoming``), so
	``allowed_qty`` -- a computed property on ``Breach``, not a field a caller can just
	declare -- comes out consistent with the rest of the fixture rather than needing to be
	hand-computed and passed in separately, the way the old fixtures did.
	"""
	baseline = on_hand + in_transit
	projected = baseline + incoming
	return Breach(
		branch=branch,
		item_code=item_code,
		row_idxs=row_idxs,
		on_hand=on_hand,
		in_transit=in_transit,
		baseline=baseline,
		incoming=incoming,
		projected=projected,
		cap=cap,
	)
