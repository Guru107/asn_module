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
