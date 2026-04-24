import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from asn_module.utils import cypress_helpers


def _as_module(path: str, **attrs) -> ModuleType:
	module = ModuleType(path)
	for key, value in attrs.items():
		setattr(module, key, value)
	return module


class _FakeLineItem:
	def __init__(self, item_code: str = "ITEM-1", qty: float = 1.0, rate: float = 10.0):
		self.name = f"ROW-{item_code}"
		self.item_code = item_code
		self.qty = qty
		self.rate = rate
		self.uom = "Nos"
		self.stock_uom = "Nos"

	def as_dict(self):
		return {
			"name": self.name,
			"item_code": self.item_code,
			"qty": self.qty,
			"rate": self.rate,
			"uom": self.uom,
			"stock_uom": self.stock_uom,
		}


class _FakePO:
	def __init__(self, name: str, *, item_count: int = 1):
		self.name = name
		self.items = [_FakeLineItem(item_code=f"ITEM-{idx + 1}") for idx in range(item_count)]


class _FakeASN:
	def __init__(self):
		self.name = "ASN-TEST-0001"
		self.status = "Submitted"
		self.supplier = "SUP-TEST"
		self.items = [SimpleNamespace(name="ASN-ITEM-1", item_code="ITEM-1", qty=10)]
		self.inserted = False
		self.submitted = False
		self.saved = False

	def insert(self, **kwargs):
		del kwargs
		self.inserted = True
		return self

	def submit(self):
		self.submitted = True
		return self

	def append(self, table, row):
		if table != "items":
			raise AssertionError("unexpected table")
		self.items.append(
			SimpleNamespace(
				name=f"ASN-ITEM-{len(self.items) + 1}",
				item_code=row["item_code"],
				qty=row["qty"],
			)
		)

	def save(self, **kwargs):
		del kwargs
		self.saved = True
		return self


class TestEnsureSupplierPortalUser(TestCase):
	def test_creates_supplier_user_permission_role_and_portal_user(self):
		supplier = MagicMock()
		supplier.name = "SUP-0001"
		supplier.insert.return_value = supplier

		new_user = MagicMock()
		new_user.name = "supplier@test.com"
		new_user.insert.return_value = new_user

		portal_user_doc = MagicMock()
		portal_user_doc.name = "supplier@test.com"
		portal_user_doc.roles = []

		portal_row = MagicMock()
		portal_row.insert.return_value = portal_row

		def fake_get_doc(arg1, arg2=None):
			if isinstance(arg1, dict) and arg1.get("doctype") == "Supplier":
				return supplier
			if isinstance(arg1, dict) and arg1.get("doctype") == "User":
				return new_user
			if isinstance(arg1, dict) and arg1.get("doctype") == "Portal User":
				return portal_row
			if arg1 == "User" and arg2 == "supplier@test.com":
				return portal_user_doc
			raise AssertionError(f"Unexpected get_doc call: {arg1}, {arg2}")

		def fake_exists(doctype, filters=None):
			if doctype == "User" and filters == "supplier@test.com":
				return False
			if doctype in {"User Permission", "Portal User"}:
				return False
			return False

		with (
			patch("asn_module.utils.cypress_helpers.frappe.db.get_value", return_value=None),
			patch("asn_module.utils.cypress_helpers.frappe.db.exists", side_effect=fake_exists),
			patch("asn_module.utils.cypress_helpers.frappe.get_doc", side_effect=fake_get_doc),
			patch("asn_module.utils.cypress_helpers.frappe.db.set_value") as set_value,
			patch("asn_module.utils.cypress_helpers.frappe.permissions.add_user_permission") as add_perm,
			patch("frappe.utils.password.update_password") as update_password,
		):
			supplier_doc, portal_user_name, portal_password = cypress_helpers._ensure_supplier_portal_user(
				supplier_name="Test Supplier",
				portal_email="supplier@test.com",
				portal_password="secret",
			)

		self.assertIs(supplier_doc, supplier)
		self.assertEqual(portal_user_name, "supplier@test.com")
		self.assertEqual(portal_password, "secret")
		set_value.assert_called_once_with("User", "supplier@test.com", "enabled", 1)
		update_password.assert_called_once_with("supplier@test.com", "secret")
		add_perm.assert_called_once_with("Supplier", "SUP-0001", "supplier@test.com")
		portal_user_doc.append.assert_called_once()
		portal_user_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_reuses_existing_rows_without_duplicate_side_effects(self):
		supplier = SimpleNamespace(name="SUP-EXISTING")
		portal_user_doc = MagicMock()
		portal_user_doc.name = "existing@test.com"
		portal_user_doc.roles = [SimpleNamespace(role="Supplier")]

		def fake_exists(doctype, filters=None):
			if doctype == "User" and filters == "existing@test.com":
				return True
			if doctype in {"User Permission", "Portal User"}:
				return True
			return False

		def fake_get_doc(arg1, arg2=None):
			if arg1 == "Supplier":
				return supplier
			if arg1 == "User":
				return portal_user_doc
			raise AssertionError(f"Unexpected get_doc call: {arg1}, {arg2}")

		with (
			patch("asn_module.utils.cypress_helpers.frappe.db.get_value", return_value="SUP-EXISTING"),
			patch("asn_module.utils.cypress_helpers.frappe.db.exists", side_effect=fake_exists),
			patch("asn_module.utils.cypress_helpers.frappe.get_doc", side_effect=fake_get_doc),
			patch("asn_module.utils.cypress_helpers.frappe.db.set_value"),
			patch("asn_module.utils.cypress_helpers.frappe.permissions.add_user_permission") as add_perm,
			patch("frappe.utils.password.update_password"),
		):
			supplier_doc, portal_user_name, _ = cypress_helpers._ensure_supplier_portal_user(
				supplier_name="Existing Supplier",
				portal_email="existing@test.com",
				portal_password="secret",
			)

		self.assertEqual(supplier_doc.name, "SUP-EXISTING")
		self.assertEqual(portal_user_name, "existing@test.com")
		add_perm.assert_not_called()
		portal_user_doc.append.assert_not_called()
		portal_user_doc.save.assert_not_called()


class TestCypressSeedHelpers(TestCase):
	def test_seed_minimal_asn_requires_test_mode(self):
		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": False}),
			patch(
				"asn_module.utils.cypress_helpers.frappe.throw",
				side_effect=frappe.ValidationError("Only available in test mode"),
			),
			self.assertRaises(frappe.ValidationError),
		):
			cypress_helpers.seed_minimal_asn()

	def test_seed_minimal_asn_happy_path(self):
		asn = _FakeASN()

		fake_asn_module = _as_module(
			"asn_module.asn_module.doctype.asn.test_asn",
			create_purchase_order=lambda **kwargs: "PO-0001",
			make_test_asn=lambda **kwargs: asn,
			real_asn_attachment_context=lambda: nullcontext(),
		)

		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": True}),
			patch("asn_module.utils.cypress_helpers.frappe.only_for"),
			patch("asn_module.utils.cypress_helpers.frappe.generate_hash", return_value="HASH1234"),
			patch.dict(sys.modules, {fake_asn_module.__name__: fake_asn_module}),
		):
			result = cypress_helpers.seed_minimal_asn()

		self.assertEqual(result["asn_name"], "ASN-TEST-0001")
		self.assertEqual(result["asn_status"], "Submitted")
		self.assertTrue(asn.inserted)
		self.assertTrue(asn.submitted)

	def test_seed_scan_station_context_happy_path(self):
		asn = _FakeASN()
		fake_asn_module = _as_module(
			"asn_module.asn_module.doctype.asn.test_asn",
			create_purchase_order=lambda **kwargs: "PO-0002",
			make_test_asn=lambda **kwargs: asn,
			real_asn_attachment_context=lambda: nullcontext(),
		)
		fake_scan_codes_module = _as_module(
			"asn_module.qr_engine.scan_codes",
			get_or_create_scan_code=lambda *args, **kwargs: "SC-0001",
		)
		register_actions = MagicMock()
		fake_setup_actions = _as_module(
			"asn_module.setup_actions",
			register_actions=register_actions,
		)

		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": True}),
			patch("asn_module.utils.cypress_helpers.frappe.only_for"),
			patch("asn_module.utils.cypress_helpers.frappe.db.get_value", return_value="CODE-1234"),
			patch.dict(
				sys.modules,
				{
					fake_asn_module.__name__: fake_asn_module,
					fake_scan_codes_module.__name__: fake_scan_codes_module,
					fake_setup_actions.__name__: fake_setup_actions,
				},
			),
		):
			result = cypress_helpers.seed_scan_station_context()

		register_actions.assert_called_once_with()
		self.assertEqual(result["scan_code_name"], "SC-0001")
		self.assertEqual(result["scan_code"], "CODE-1234")

	def test_seed_supplier_context_and_large_po(self):
		supplier = SimpleNamespace(name="SUP-PORTAL")
		po_one = _FakePO("PO-ONE")
		po_two = _FakePO("PO-TWO")
		po_large = _FakePO("PO-LARGE", item_count=100)

		create_purchase_order = MagicMock(side_effect=[po_one, po_two, po_large])
		fake_asn_module = _as_module(
			"asn_module.asn_module.doctype.asn.test_asn",
			create_purchase_order=create_purchase_order,
		)

		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": True}),
			patch("asn_module.utils.cypress_helpers.frappe.only_for"),
			patch(
				"asn_module.utils.cypress_helpers._ensure_supplier_portal_user",
				return_value=(supplier, "portal@test.com", "pw"),
			),
			patch.dict(sys.modules, {fake_asn_module.__name__: fake_asn_module}),
		):
			context = cypress_helpers.seed_supplier_context()
			large_context = cypress_helpers.seed_supplier_large_po_context()

		self.assertEqual(context["supplier"], "SUP-PORTAL")
		self.assertEqual(len(context["purchase_orders"]), 2)
		self.assertEqual(large_context["purchase_order"]["name"], "PO-LARGE")
		self.assertEqual(len(large_context["purchase_order"]["items"]), 100)

	def test_seed_asn_with_items_happy_path(self):
		asn = _FakeASN()
		po_one = _FakePO("PO-BASE")
		po_two = _FakePO("PO-SECOND")
		fake_asn_module = _as_module(
			"asn_module.asn_module.doctype.asn.test_asn",
			create_purchase_order=MagicMock(side_effect=[po_one, po_two]),
			make_test_asn=lambda **kwargs: asn,
			real_asn_attachment_context=lambda: nullcontext(),
		)

		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": True}),
			patch("asn_module.utils.cypress_helpers.frappe.only_for"),
			patch.dict(sys.modules, {fake_asn_module.__name__: fake_asn_module}),
		):
			result = cypress_helpers.seed_asn_with_items()

		self.assertEqual(result["item_count"], 2)
		self.assertTrue(asn.saved)
		self.assertTrue(asn.submitted)

	def test_seed_quality_inspection_context_happy_path(self):
		asn = _FakeASN()
		fake_asn_module = _as_module(
			"asn_module.asn_module.doctype.asn.test_asn",
			create_purchase_order=lambda **kwargs: "PO-1000",
			make_test_asn=lambda **kwargs: asn,
			real_asn_attachment_context=lambda: nullcontext(),
		)

		class _Fixture:
			def _make_purchase_receipt_with_qi(self, *args, **kwargs):
				del args, kwargs
				return [SimpleNamespace(name="PR-0001")]

			def _make_quality_inspection(self, *args, **kwargs):
				del args, kwargs
				if not hasattr(self, "_count"):
					self._count = 0
				self._count += 1
				return SimpleNamespace(name=f"QI-{self._count}")

		fake_stock_transfer_tests = _as_module(
			"asn_module.handlers.tests.test_stock_transfer",
			TestCreateStockTransfer=_Fixture,
		)

		with (
			patch.dict("asn_module.utils.cypress_helpers.frappe.conf", {"allow_tests": True}),
			patch("asn_module.utils.cypress_helpers.frappe.only_for"),
			patch.dict(
				sys.modules,
				{
					fake_asn_module.__name__: fake_asn_module,
					fake_stock_transfer_tests.__name__: fake_stock_transfer_tests,
				},
			),
		):
			result = cypress_helpers.seed_quality_inspection_context()

		self.assertEqual(result["asn_name"], "ASN-TEST-0001")
		self.assertEqual(result["pr_name"], "PR-0001")
		self.assertEqual(result["qi_accepted"], "QI-1")
		self.assertEqual(result["qi_rejected"], "QI-2")
