import frappe

from asn_module.tests.compat import IntegrationTestCase
from asn_module.utils.test_setup import before_tests


def _ensure_branch(name: str) -> str:
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)
	return name


def _ensure_warehouse(name: str, is_group: int = 0) -> str:
	company = frappe.db.get_value("Company", {}, "name")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full_name = f"{name} - {abbr}"
	if frappe.db.exists("Warehouse", full_name):
		return full_name

	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": name,
			"company": company,
			"is_group": is_group,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_settings(branch: str, warehouses: list[str], enabled: int = 1):
	doc = frappe.get_doc(
		{
			"doctype": "ASN Stock Cap Settings",
			"branch": branch,
			"enabled": enabled,
			"warehouses": [{"warehouse": w} for w in warehouses],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestStockCapSettings(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()

	def setUp(self):
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")

	def test_settings_document_is_named_after_branch(self):
		branch = _ensure_branch("_Test Cap Branch A")
		warehouse = _ensure_warehouse("_Test Cap WH A")
		doc = _make_settings(branch, [warehouse])
		self.assertEqual(doc.name, branch)

	def test_group_warehouse_is_rejected(self):
		branch = _ensure_branch("_Test Cap Branch B")
		group = _ensure_warehouse("_Test Cap Group", is_group=1)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_settings(branch, [group])
		self.assertIn("group warehouse", str(ctx.exception).lower())

	def test_duplicate_warehouse_in_same_document_is_rejected(self):
		branch = _ensure_branch("_Test Cap Branch C")
		warehouse = _ensure_warehouse("_Test Cap WH C")
		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_settings(branch, [warehouse, warehouse])
		self.assertIn("listed twice", str(ctx.exception).lower())

	def test_warehouse_claimed_by_another_branch_is_rejected(self):
		first = _ensure_branch("_Test Cap Branch D")
		second = _ensure_branch("_Test Cap Branch E")
		warehouse = _ensure_warehouse("_Test Cap WH D")
		_make_settings(first, [warehouse])
		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_settings(second, [warehouse])
		self.assertIn(first, str(ctx.exception))

	def test_claim_error_names_the_current_branch_not_the_document_name(self):
		first = _ensure_branch("_Test Cap Branch F")
		renamed = _ensure_branch("_Test Cap Branch F Renamed")
		second = _ensure_branch("_Test Cap Branch G")
		warehouse = _ensure_warehouse("_Test Cap WH F")
		settings = _make_settings(first, [warehouse])
		# A Branch rename updates the branch field but leaves the document name alone.
		frappe.db.set_value("ASN Stock Cap Settings", settings.name, "branch", renamed)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_make_settings(second, [warehouse])
		self.assertIn(renamed, str(ctx.exception))
