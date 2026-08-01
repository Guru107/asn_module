from contextlib import contextmanager

import frappe
from frappe.permissions import add_permission
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
from asn_module.stock_cap.api import get_stock_cap_preview
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
