import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.utils.test_setup import before_tests, disable_hsn_validation

BRANCH = "_Test Cap Branch Item"
ITEM = "_Test Cap Item"


def _ensure_branch(name: str) -> str:
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)
	return name


def _ensure_item(code: str) -> str:
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": frappe.db.get_value("Item Group", {}, "name"),
				"stock_uom": frappe.db.get_value("UOM", {}, "name"),
			}
		).insert(ignore_permissions=True)
	return code


def _ensure_warehouse(name: str) -> str:
	company = frappe.db.get_value("Company", {}, "name")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full_name = f"{name} - {abbr}"
	if not frappe.db.exists("Warehouse", full_name):
		frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": name, "company": company, "is_group": 0}
		).insert(ignore_permissions=True)
	return full_name


def _make_cap(branch: str, item: str, max_qty: float = 100.0):
	return frappe.get_doc(
		{"doctype": "ASN Item Branch Cap", "branch": branch, "item": item, "max_qty": max_qty}
	).insert(ignore_permissions=True)


class TestASNItemBranchCap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()
		_ensure_branch(BRANCH)
		_ensure_item(ITEM)

	def setUp(self):
		frappe.db.delete("ASN Item Branch Cap")
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")

	def _configure_branch(self, branch: str):
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": branch,
				"enabled": 1,
				"warehouses": [{"warehouse": _ensure_warehouse("_Test Cap Item WH")}],
			}
		).insert(ignore_permissions=True)

	def test_data_import_is_enabled(self):
		self.assertTrue(frappe.get_meta("ASN Item Branch Cap").allow_import)

	def test_document_is_named_after_branch_and_item(self):
		self._configure_branch(BRANCH)
		doc = _make_cap(BRANCH, ITEM)
		self.assertEqual(doc.name, f"{BRANCH}::{ITEM}")

	def test_second_row_for_same_item_and_branch_is_rejected(self):
		self._configure_branch(BRANCH)
		_make_cap(BRANCH, ITEM)
		with self.assertRaises(frappe.DuplicateEntryError):
			_make_cap(BRANCH, ITEM, max_qty=50)

	def test_same_item_in_another_branch_is_allowed(self):
		self._configure_branch(BRANCH)
		other = _ensure_branch("_Test Cap Branch Item B")
		_make_cap(BRANCH, ITEM, max_qty=200)
		doc = _make_cap(other, ITEM, max_qty=50)
		self.assertEqual(doc.max_qty, 50)

	def test_separator_in_branch_or_item_is_rejected(self):
		self._configure_branch(BRANCH)
		bad_branch = _ensure_branch("_Test::Cap Branch")

		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_cap(bad_branch, ITEM)

		self.assertIn("::", str(ctx.exception))

	def test_negative_max_qty_is_rejected(self):
		self._configure_branch(BRANCH)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_cap(BRANCH, ITEM, max_qty=-1)
		self.assertIn("negative", str(ctx.exception).lower())

	def test_unconfigured_branch_warns_without_blocking(self):
		frappe.local.message_log = []
		doc = _make_cap(BRANCH, ITEM)

		self.assertTrue(frappe.db.exists("ASN Item Branch Cap", doc.name))
		messages = " ".join(str(m) for m in frappe.local.message_log or [])
		self.assertIn("not be enforced", messages)

	def test_configured_branch_saves_without_warning(self):
		self._configure_branch(BRANCH)
		frappe.local.message_log = []
		_make_cap(BRANCH, ITEM)

		messages = " ".join(str(m) for m in frappe.local.message_log or [])
		self.assertNotIn("not be enforced", messages)

	def test_warning_does_not_spuriously_fire_after_branch_rename(self):
		"""Reproduces the same stale-name defect ``d31e4bd`` fixed in
		``stock_cap/fetch.py::_fetch_cap_warehouses``, but for
		``_warn_if_branch_has_no_cap_warehouses``. ``ASN Stock Cap Settings`` autonames from
		``branch`` (``autoname: "field:branch"``) but has no rename handling, and Frappe's
		``rename_doc`` updates only the settings document's ``branch`` field -- it never
		renames the document itself. Configure a branch with real cap warehouses, rename the
		branch, then set a cap for the new name: before the fix, looking the settings document
		up by ``self.branch`` (its post-rename name) finds nothing, because the settings
		document still carries its pre-rename name -- so ``settings`` comes back ``None`` and
		the code falls through to the "not enforced" warning even though the branch is, in
		fact, fully configured. That is a spurious warning for a properly configured branch,
		the same class of silent breakage the fetch.py fix addressed, just surfacing as a
		wrong warning instead of a silently-skipped cap check.
		"""
		branch = _ensure_branch("_Test Cap Branch For Rename")
		self._configure_branch(branch)

		new_branch = f"{branch} Renamed"
		if frappe.db.exists("Branch", new_branch):
			frappe.delete_doc("Branch", new_branch, ignore_permissions=True, force=True)

		try:
			frappe.rename_doc("Branch", branch, new_branch, force=True)

			settings_name = frappe.db.get_value("ASN Stock Cap Settings", {"branch": new_branch}, "name")
			self.assertEqual(
				settings_name,
				branch,
				"the settings document must keep its old (stale) name across the rename -- "
				"that stale name is exactly what this regression guards against",
			)

			frappe.local.message_log = []
			_make_cap(new_branch, ITEM)

			messages = " ".join(str(m) for m in frappe.local.message_log or [])
			self.assertNotIn("not be enforced", messages)
		finally:
			if frappe.db.exists("Branch", new_branch):
				frappe.rename_doc("Branch", new_branch, branch, force=True)

	def test_blank_branch_skips_the_warehouse_warning_check(self):
		"""``_warn_if_branch_has_no_cap_warehouses`` guards on ``self.branch`` before it ever
		queries ASN Stock Cap Settings. Mandatory-field validation normally stops a blank
		branch from reaching here, but ``validate()`` runs before that check in Frappe's
		save pipeline (see ``run_before_save_methods`` vs. ``_validate_mandatory``), so this
		guard clause is live code, not dead code, and deserves its own direct test rather
		than one that depends on that ordering.
		"""
		frappe.local.message_log = []
		doc = frappe.get_doc({"doctype": "ASN Item Branch Cap", "branch": "", "item": ITEM, "max_qty": 10})

		doc.validate()

		messages = " ".join(str(m) for m in frappe.local.message_log or [])
		self.assertNotIn("not be enforced", messages)

	def test_duplicate_pair_after_rename_is_rejected(self):
		"""Reproduces the post-rename state the duplicate guard exists for: ``rename_doc``
		updates a cap row's ``branch``/``item`` Link values but never re-derives or renames
		the document itself, so a stale-named row's columns can already describe a pair that
		a fresh row is about to be created for. Forcing a distinct name via
		``flags.name_set`` stands in for an actual Branch/Item rename -- it produces the same
		"columns match, names differ" shape without depending on ``rename_doc`` machinery,
		keeping the test fast and focused on the guard itself.
		"""
		self._configure_branch(BRANCH)
		_make_cap(BRANCH, ITEM, max_qty=200)

		stale = frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": ITEM, "max_qty": 50}
		)
		stale.name = "_Test Stale Renamed Cap Row"
		stale.flags.name_set = True

		with self.assertRaises(frappe.ValidationError) as ctx:
			stale.insert(ignore_permissions=True)

		self.assertIn("already exists", str(ctx.exception))

	def test_zero_max_qty_is_saveable(self):
		self._configure_branch(BRANCH)
		doc = _make_cap(BRANCH, ITEM, max_qty=0)

		persisted_max_qty = frappe.db.get_value("ASN Item Branch Cap", doc.name, "max_qty")
		self.assertEqual(persisted_max_qty, 0)

	def test_editing_maximum_stock_records_a_version(self):
		self._configure_branch(BRANCH)
		doc = _make_cap(BRANCH, ITEM, max_qty=100)
		frappe.db.delete("Version", {"ref_doctype": doc.doctype, "docname": doc.name})

		doc.max_qty = 40
		doc.save(ignore_permissions=True, ignore_version=False)

		rows = frappe.get_all(
			"Version",
			filters={"ref_doctype": doc.doctype, "docname": doc.name},
			fields=["data"],
		)
		self.assertEqual(len(rows), 1)
		self.assertIn("max_qty", rows[0].data)
