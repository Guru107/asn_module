import json
from contextlib import contextmanager
from types import SimpleNamespace

import frappe
from frappe.permissions import add_permission
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	create_purchase_order,
	make_test_asn,
)
from asn_module.stock_cap.api import breaches_for_purchase_receipt, get_stock_cap_preview
from asn_module.stock_cap.messages import may_see_stock_figures
from asn_module.utils.permissions import get_accessible_doc
from asn_module.utils.test_setup import (
	before_tests,
	build_purchase_order_with_mandatory_fields,
	disable_hsn_validation,
)

BRANCH = "_Test API Access Branch"
ITEM = "_Test API Access Item"
MAX_STOCK = 5

# Real, minimally-privileged roles -- one grants Purchase Order read only, one grants
# both Purchase Order and Item read, one grants neither. Exercising the actual Frappe
# permission engine (rather than monkeypatching frappe.has_permission) is what proves
# the redaction seam and the shared access gate hold up under real permission checks.
PO_ONLY_ROLE = "_Test Stock Cap PO Only"
FULL_ROLE = "_Test Stock Cap Full Access"
NO_ACCESS_ROLE = "_Test Stock Cap No Access"

PO_ONLY_USER = "asn.stock.cap.po.only@asn-module.test"
FULL_USER = "asn.stock.cap.full@asn-module.test"
NO_ACCESS_USER = "asn.stock.cap.none@asn-module.test"


def _create_purchase_order(**kwargs) -> "frappe.model.document.Document":
	"""Build a real Purchase Order fixture, filling in bench-specific mandatory fields.

	See asn_module.utils.test_setup.build_purchase_order_with_mandatory_fields for why
	this bench-specific mandatory-field workaround is needed. Never submits -- callers in
	this module only need a saved (not necessarily submitted) Purchase Order.
	"""
	return build_purchase_order_with_mandatory_fields(
		create_purchase_order,
		tax_description="_Test Stock Cap Access Tax",
		do_not_submit=True,
		**kwargs,
	)


def _ensure_role(role_name: str) -> str:
	if not frappe.db.exists("Role", role_name):
		frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
	return role_name


def _ensure_role_permission(doctype: str, role: str) -> None:
	if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "read": 1}):
		return
	add_permission(doctype, role, permlevel=0)


def _ensure_user(email: str, roles: tuple[str, ...]) -> str:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "ASN Stock Cap Test",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		user.insert(ignore_permissions=True)

	existing_roles = {r.role for r in (user.roles or [])}
	desired_roles = set(roles)
	if existing_roles != desired_roles:
		user.set("roles", [])
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	return email


@contextmanager
def _as_user(email: str):
	"""Run code as ``email``, restoring the previous session user afterward."""
	previous = frappe.session.user
	frappe.set_user(email)
	try:
		yield
	finally:
		frappe.set_user(previous)


class TestStockCapPreviewAccessControl(FrappeTestCase):
	"""Covers the stock_cap security seam: get_stock_cap_preview, may_see_stock_figures,
	and the shared Purchase Order access gate under real, role-based permission checks.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

		if not frappe.db.exists("Branch", BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": ITEM,
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				}
			).insert(ignore_permissions=True)

		_ensure_role(PO_ONLY_ROLE)
		_ensure_role(FULL_ROLE)
		_ensure_role(NO_ACCESS_ROLE)

		_ensure_role_permission("Purchase Order", PO_ONLY_ROLE)
		_ensure_role_permission("Purchase Order", FULL_ROLE)
		_ensure_role_permission("Item", FULL_ROLE)
		# NO_ACCESS_ROLE deliberately gets no Custom DocPerm rows at all.

		_ensure_user(PO_ONLY_USER, (PO_ONLY_ROLE,))
		_ensure_user(FULL_USER, (FULL_ROLE,))
		_ensure_user(NO_ACCESS_USER, (NO_ACCESS_ROLE,))

	def setUp(self):
		frappe.set_user("Administrator")
		# FrappeTestCase only rolls back once at class teardown, not per test, so clear
		# this class's own cap-settings fixtures before each test.
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.db.set_value("Item", ITEM, "custom_max_stock", MAX_STOCK)

		self.po = _create_purchase_order(item_code=ITEM, qty=10)
		frappe.db.set_value("Purchase Order", self.po.name, "branch", BRANCH)
		self.warehouse = self.po.items[0].warehouse

		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": BRANCH,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

		# Comfortably above MAX_STOCK with zero on-hand/in-transit, so this always breaches.
		self.items = [
			{
				"purchase_order": self.po.name,
				"purchase_order_item": self.po.items[0].name,
				"item_code": ITEM,
				"qty": MAX_STOCK * 100,
				"idx": 1,
			}
		]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_preview_withholds_stock_figures_without_item_read(self):
		with _as_user(PO_ONLY_USER):
			preview = get_stock_cap_preview(self.items)

		self.assertEqual(len(preview), 1)
		entry = preview[0]
		self.assertEqual(entry["item_code"], ITEM)
		self.assertEqual(entry["row_idxs"], [1])
		self.assertTrue(entry["breached"])
		self.assertIn("allowed_qty", entry)
		for withheld_key in ("branch", "on_hand", "in_transit", "projected", "cap"):
			self.assertNotIn(withheld_key, entry)

	def test_preview_includes_stock_figures_with_item_read(self):
		with _as_user(FULL_USER):
			preview = get_stock_cap_preview(self.items)

		self.assertEqual(len(preview), 1)
		entry = preview[0]
		self.assertEqual(entry["branch"], BRANCH)
		for included_key in ("on_hand", "in_transit", "projected", "cap"):
			self.assertIn(included_key, entry)

	def test_preview_rejects_caller_without_purchase_order_access(self):
		with _as_user(NO_ACCESS_USER):
			with self.assertRaises(frappe.PermissionError):
				get_stock_cap_preview(self.items)

	def test_preview_does_not_reject_caller_with_purchase_order_access(self):
		with _as_user(PO_ONLY_USER):
			preview = get_stock_cap_preview(self.items)

		self.assertEqual(len(preview), 1)

	def test_preview_accepts_json_encoded_items_string(self):
		"""frappe.call's default serialization sends list/dict RPC args as a JSON string
		when the target has no type hint frappe's request layer can deserialize against.
		get_stock_cap_preview must decode that itself.
		"""
		with _as_user(PO_ONLY_USER):
			preview = get_stock_cap_preview(json.dumps(self.items))

		self.assertEqual(len(preview), 1)
		self.assertEqual(preview[0]["item_code"], ITEM)

	def test_preview_skips_rows_without_a_purchase_order(self):
		rows = [{"idx": 1, "item_code": ITEM, "qty": MAX_STOCK * 100}, *self.items]

		with _as_user(PO_ONLY_USER):
			preview = get_stock_cap_preview(rows)

		self.assertEqual(len(preview), 1)

	def test_permission_gate_rejects_caller_without_purchase_order_access(self):
		with _as_user(NO_ACCESS_USER):
			with self.assertRaises(frappe.PermissionError):
				get_accessible_doc("Purchase Order", self.po.name)

	def test_permission_gate_allows_caller_with_purchase_order_access(self):
		with _as_user(PO_ONLY_USER):
			doc = get_accessible_doc("Purchase Order", self.po.name)

		self.assertEqual(doc.name, self.po.name)

	def test_may_see_stock_figures_true_when_caller_can_read_item(self):
		with _as_user(FULL_USER):
			self.assertTrue(may_see_stock_figures())

	def test_may_see_stock_figures_false_when_caller_cannot_read_item(self):
		with _as_user(PO_ONLY_USER):
			self.assertFalse(may_see_stock_figures())


PR_BRANCH = "_Test API PR Branch"
PR_ITEM = "_Test API PR Item"
PR_MAX_STOCK = 5


class TestBreachesForPurchaseReceipt(FrappeTestCase):
	"""breaches_for_purchase_receipt is asn_module's third enforcement surface (the other
	two, breaches_for_asn_rows and get_stock_cap_preview, are exercised above). The
	Purchase Receipt handler's own tests mock this function out entirely, so nothing else
	in the suite calls the real implementation end to end.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
		disable_hsn_validation()

		if not frappe.db.exists("Branch", PR_BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": PR_BRANCH}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item", PR_ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": PR_ITEM,
					"item_name": PR_ITEM,
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		# FrappeTestCase only rolls back once at class teardown, not per test, so a
		# submitted ASN inserted by an earlier test in this class (e.g.
		# test_receipt_not_linked_to_its_asn_is_not_double_counted) would otherwise keep
		# contributing to later tests' in-transit totals.
		stale_asn_names = frappe.get_all("ASN Item", filters={"item_code": PR_ITEM}, pluck="parent")
		if stale_asn_names:
			frappe.db.delete("ASN Item", {"parent": ["in", stale_asn_names]})
			frappe.db.delete("ASN", {"name": ["in", stale_asn_names]})
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.db.set_value("Item", PR_ITEM, "custom_max_stock", PR_MAX_STOCK)

		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API Tax",
			do_not_submit=True,
			item_code=PR_ITEM,
			qty=10,
		)
		self.warehouse = po.items[0].warehouse

		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": PR_BRANCH,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

	def _receipt_row(self, **overrides):
		defaults = {
			"idx": 1,
			"item_code": PR_ITEM,
			"warehouse": self.warehouse,
			"stock_qty": 0.0,
			"rejected_qty": 0.0,
			"rejected_warehouse": None,
			"conversion_factor": 1.0,
			"purchase_order_item": None,
		}
		defaults.update(overrides)
		return SimpleNamespace(**defaults)

	def test_receipt_over_cap_returns_a_breach(self):
		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			asn=None,
			items=[self._receipt_row(stock_qty=PR_MAX_STOCK * 2)],
		)

		breaches = breaches_for_purchase_receipt(doc)

		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].branch, PR_BRANCH)
		self.assertEqual(breaches[0].item_code, PR_ITEM)
		self.assertEqual(breaches[0].cap, PR_MAX_STOCK)

	def test_receipt_within_cap_returns_no_breach(self):
		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			asn=None,
			items=[self._receipt_row(stock_qty=PR_MAX_STOCK - 1)],
		)

		self.assertEqual(breaches_for_purchase_receipt(doc), [])

	def test_return_receipt_short_circuits_before_any_lookup(self):
		"""is_return=1 makes collect_lines_from_purchase_receipt return [] up front, so
		breaches_for_purchase_receipt must return [] without touching fetch_cap_context at
		all -- covers its own early-return branch, distinct from evaluate()'s.
		"""
		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=1,
			asn=None,
			items=[self._receipt_row(stock_qty=-(PR_MAX_STOCK * 2))],
		)

		self.assertEqual(breaches_for_purchase_receipt(doc), [])

	def test_receipt_not_linked_to_its_asn_is_not_double_counted(self):
		"""Nothing disables the standard Purchase Order -> Create -> Purchase Receipt
		action, which leaves Purchase Receipt.asn empty -- handlers/purchase_receipt.py:
		create_from_asn is the only place that sets it. breaches_for_purchase_receipt must
		not double-count such a receipt's goods (once as the submitted ASN's in-transit
		quantity, again as this receipt's own incoming) even though it has no ASN name to
		exclude by; it must exclude by the Purchase Order Item instead.
		"""
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API Unlinked Tax",
			item_code=PR_ITEM,
			qty=10,
		)
		po_item = po.items[0]

		asn = make_test_asn(purchase_order=po, qty=PR_MAX_STOCK)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[
				self._receipt_row(
					warehouse=po_item.warehouse,
					stock_qty=PR_MAX_STOCK,
					purchase_order_item=po_item.name,
				)
			],
		)

		self.assertEqual(breaches_for_purchase_receipt(doc), [])
