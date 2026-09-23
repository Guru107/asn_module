import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.permissions import add_permission
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import (
	_mock_asn_attachments,
	create_purchase_order,
	make_test_asn,
)
from asn_module.handlers.purchase_receipt import on_purchase_receipt_cancel, on_purchase_receipt_submit
from asn_module.stock_cap.api import breaches_for_asn_rows, breaches_for_purchase_receipt
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures
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


class TestStockCapAccessControlAndRedaction(FrappeTestCase):
	"""Covers the stock_cap security seam: may_see_stock_figures + format_breaches
	redaction, and the shared Purchase Order access gate, under real, role-based
	permission checks.
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
		frappe.db.delete("ASN Item Branch Cap", {"item": ITEM})
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": ITEM, "max_qty": MAX_STOCK}
		).insert(ignore_permissions=True)

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

	def test_breach_message_withholds_stock_figures_without_item_read(self):
		"""Same real-world path the ASN controller, Purchase Receipt handler, and portal
		bulk upload all use: format_breaches(breaches, detailed=may_see_stock_figures()).
		"""
		with _as_user(PO_ONLY_USER):
			breaches, _accepted = breaches_for_asn_rows(self.items)
			message = format_breaches(breaches, detailed=may_see_stock_figures())

		self.assertEqual(len(breaches), 1)
		self.assertIn(ITEM, message)
		for withheld_text in ("branch", "on hand", "in transit"):
			self.assertNotIn(withheld_text, message.lower())

	def test_breach_message_includes_stock_figures_with_item_read(self):
		with _as_user(FULL_USER):
			breaches, _accepted = breaches_for_asn_rows(self.items)
			message = format_breaches(breaches, detailed=may_see_stock_figures())

		self.assertEqual(len(breaches), 1)
		self.assertIn(BRANCH, message)
		for included_text in ("on hand", "in transit"):
			self.assertIn(included_text, message.lower())

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
	"""breaches_for_purchase_receipt is asn_module's second enforcement surface (the other,
	breaches_for_asn_rows, is exercised above). The Purchase Receipt handler's own tests
	mock this function out entirely, so nothing else in the suite calls the real
	implementation end to end.
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
		frappe.db.delete("ASN Item Branch Cap", {"item": PR_ITEM})
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": PR_BRANCH, "item": PR_ITEM, "max_qty": PR_MAX_STOCK}
		).insert(ignore_permissions=True)

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

	def test_partial_receipt_breach_from_the_undelivered_remainder_is_refused(self):
		"""Regression for the in-transit under-count: an ASN ships 10 units and none of it
		is received yet, so a receipt taking only 3 of those units must still see the other
		7 counted as in-transit. Excluding the whole Purchase Order Item's ASN Item rows (the
		old behaviour) would drop all 10 shipped units instead of just the 3 this receipt
		takes, letting a receipt that genuinely breaches the ceiling through unrefused.

		The Purchase Order built here is never given a ``branch``, so the ASN's own
		before_submit cap check (which needs the Purchase Order's branch to derive any
		lines at all -- see collect.py:collect_lines_from_asn_rows) is a no-op and does
		not block the 10-unit shipment; only breaches_for_purchase_receipt, exercised
		directly below, is under test here.
		"""
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API Partial Tax",
			item_code=PR_ITEM,
			qty=10,
		)
		po_item = po.items[0]

		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[
				self._receipt_row(
					warehouse=po_item.warehouse,
					stock_qty=3,
					purchase_order_item=po_item.name,
				)
			],
		)

		breaches = breaches_for_purchase_receipt(doc)

		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].item_code, PR_ITEM)
		self.assertEqual(breaches[0].cap, PR_MAX_STOCK)

	def test_two_asns_for_the_same_po_item_the_others_shipment_still_breaches(self):
		"""A single Purchase Order Item can be shipped across more than one ASN. A receipt
		that exactly covers one ASN's shipment must not remove the other ASN's still-
		undelivered quantity from in-transit -- only the receiving quantity this receipt
		actually covers comes off.

		As in test_partial_receipt_breach_from_the_undelivered_remainder_is_refused, the
		Purchase Order is never given a ``branch``, so neither ASN's own before_submit cap
		check blocks its shipment; breaches_for_purchase_receipt is exercised directly.
		"""
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API TwoASN Tax",
			item_code=PR_ITEM,
			qty=20,
		)
		po_item = po.items[0]

		asn_a = make_test_asn(purchase_order=po, qty=8)
		asn_a.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn_a.submit()

		asn_b = make_test_asn(purchase_order=po, qty=8)
		asn_b.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn_b.submit()

		# setUp's cap of PR_MAX_STOCK (5) would already breach on ASN A's 8 units alone,
		# which would make this test indistinguishable from the simpler single-ASN
		# partial-receipt case above. 12 sits strictly between one ASN's shipment (8) and
		# both combined (16), so only correctly keeping ASN B's 8 units counted -- not
		# ASN A's -- distinguishes a fixed in-transit total from a buggy one.
		cap_name = f"{PR_BRANCH}::{PR_ITEM}"
		frappe.db.set_value("ASN Item Branch Cap", cap_name, "max_qty", 12, update_modified=False)

		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[
				self._receipt_row(
					warehouse=po_item.warehouse,
					stock_qty=8,
					purchase_order_item=po_item.name,
				)
			],
		)

		breaches = breaches_for_purchase_receipt(doc)

		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].item_code, PR_ITEM)
		self.assertEqual(breaches[0].cap, 12)

	def _receive_with_partial_rejection(self, *, asn, accepted: float, rejected: float):
		"""Drive the real on_purchase_receipt_submit handler for a receipt that accepts
		``accepted`` units and rejects ``rejected`` -- both splits of the same shipped ASN
		Item row -- persisting whatever received_qty the handler under test computes.
		"""
		asn_item_name = asn.items[0].name
		pr_doc = SimpleNamespace(
			asn=asn.name,
			asn_items=json.dumps({"1": {"asn_item_name": asn_item_name, "original_qty": asn.items[0].qty}}),
			items=[SimpleNamespace(idx=1, qty=accepted, rejected_qty=rejected, item_code=PR_ITEM)],
			name="PR-REJECT-DRAIN-0001",
		)

		with (
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition"),
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZQ=="}),
			patch("asn_module.handlers.purchase_receipt.attach_qr_to_doc"),
			patch("asn_module.handlers.purchase_receipt.frappe.get_cached_value", return_value=True),
		):
			on_purchase_receipt_submit(pr_doc, "on_submit")

		return asn_item_name

	def test_partial_rejection_drains_in_transit_fully(self):
		"""Finding 2: rejected units still arrived -- they just landed in the rejection
		warehouse instead of the accepted one. on_purchase_receipt_submit must persist
		received_qty as the full delivered amount (accepted + rejected), not accepted alone,
		so this ASN Item's contribution to In Transit (fetch.py:_fetch_in_transit reads
		``ai.qty - received_qty``) drains to zero once the whole shipment has arrived, rather
		than leaving the rejected portion stranded as phantom in-transit forever.
		"""
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API RejectDrain Tax",
			item_code=PR_ITEM,
			qty=10,
		)

		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		asn_item_name = self._receive_with_partial_rejection(asn=asn, accepted=6, rejected=4)

		self.assertEqual(frappe.db.get_value("ASN Item", asn_item_name, "received_qty"), 10)

	def test_later_receipt_for_the_same_item_is_not_blocked_by_an_earlier_rejection(self):
		"""Companion to test_partial_rejection_drains_in_transit_fully, using a *second*,
		distinct Purchase Order Item for the same item_code/warehouse so the later receipt's
		own receiving-quantity exclusion (which only excludes its own Purchase Order Item)
		cannot coincidentally swallow the earlier one's leftover -- that would make this test
		pass even without the fix. Item X ships twice: once via po_item_a (10 units, 6
		accepted / 4 rejected), once via po_item_b (5 units, still fully in transit). A
		receipt for po_item_b's own 5 units must weigh only its own incoming quantity against
		the cap, not a phantom 4 units left behind by po_item_a's rejection. Before the fix,
		received_qty on po_item_a's ASN Item stayed at 6 (accepted only), so
		ai.qty - received_qty kept counting the rejected 4 as still in-transit, pushing this
		receipt over PR_MAX_STOCK (5) when it should land exactly on it.
		"""
		po_a = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API RejectNoBlock Tax A",
			item_code=PR_ITEM,
			qty=10,
		)
		asn_a = make_test_asn(purchase_order=po_a, qty=10)
		asn_a.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn_a.submit()

		self._receive_with_partial_rejection(asn=asn_a, accepted=6, rejected=4)

		po_b = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API RejectNoBlock Tax B",
			item_code=PR_ITEM,
			warehouse=po_a.items[0].warehouse,
			supplier=po_a.supplier,
			qty=PR_MAX_STOCK,
		)
		po_item_b = po_b.items[0]
		asn_b = make_test_asn(purchase_order=po_b, qty=PR_MAX_STOCK)
		asn_b.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn_b.submit()

		doc = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[
				self._receipt_row(
					warehouse=po_item_b.warehouse,
					stock_qty=PR_MAX_STOCK,
					purchase_order_item=po_item_b.name,
				)
			],
		)

		self.assertEqual(breaches_for_purchase_receipt(doc), [])

	def test_unlinked_receipt_submit_drains_in_transit(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API Unlinked Drain Tax",
			item_code=PR_ITEM,
			qty=10,
		)
		po_item = po.items[0]
		asn = make_test_asn(purchase_order=po, qty=PR_MAX_STOCK)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		on_purchase_receipt_submit(
			SimpleNamespace(
				asn=None,
				is_return=0,
				name="PR-UNLINKED-DRAIN",
				items=[
					SimpleNamespace(
						idx=1,
						qty=PR_MAX_STOCK,
						stock_qty=PR_MAX_STOCK,
						rejected_qty=0,
						conversion_factor=1,
						purchase_order_item=po_item.name,
						item_code=PR_ITEM,
					)
				],
			),
			"on_submit",
		)

		self.assertEqual(frappe.db.get_value("ASN Item", asn.items[0].name, "received_qty"), PR_MAX_STOCK)
		later = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[self._receipt_row(warehouse=po_item.warehouse, stock_qty=1, purchase_order_item="OTHER-POI")],
		)
		self.assertEqual(breaches_for_purchase_receipt(later), [])

	def test_received_qty_uses_purchase_uom_when_the_receipt_uom_differs(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API UOM Tax",
			item_code=PR_ITEM,
			qty=24,
		)
		po_item = po.items[0]
		frappe.db.set_value("Purchase Order Item", po_item.name, "conversion_factor", 1)
		asn = make_test_asn(purchase_order=po, qty=24)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		with (
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition"),
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZQ=="}),
			patch("asn_module.handlers.purchase_receipt.attach_qr_to_doc"),
			patch("asn_module.handlers.purchase_receipt.frappe.get_cached_value", return_value=True),
		):
			on_purchase_receipt_submit(
				SimpleNamespace(
					asn=asn.name,
					is_return=0,
					name="PR-UOM-DRAIN",
					asn_items=json.dumps({"1": {"asn_item_name": asn.items[0].name}}),
					items=[
						SimpleNamespace(
							idx=1,
							qty=2,
							stock_qty=24,
							rejected_qty=0,
							conversion_factor=12,
							purchase_order_item=po_item.name,
							item_code=PR_ITEM,
						)
					],
				),
				"on_submit",
			)

		self.assertEqual(frappe.db.get_value("ASN Item", asn.items[0].name, "received_qty"), 24)

	def test_cancelling_a_receipt_puts_the_shipment_back_in_transit(self):
		po = build_purchase_order_with_mandatory_fields(
			create_purchase_order,
			tax_description="_Test Stock Cap PR API Cancel Tax",
			item_code=PR_ITEM,
			qty=10,
		)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		with _mock_asn_attachments():
			asn.submit()

		pr_doc = SimpleNamespace(
			asn=asn.name,
			is_return=0,
			name="PR-CANCEL-DRAIN",
			asn_items=json.dumps({"1": {"asn_item_name": asn.items[0].name}}),
			items=[SimpleNamespace(idx=1, qty=10, rejected_qty=0, item_code=PR_ITEM)],
		)
		with (
			patch("asn_module.handlers.purchase_receipt.emit_asn_item_transition"),
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZQ=="}),
			patch("asn_module.handlers.purchase_receipt.attach_qr_to_doc"),
			patch("asn_module.handlers.purchase_receipt.frappe.get_cached_value", return_value=True),
		):
			on_purchase_receipt_submit(pr_doc, "on_submit")

		asn.reload()
		self.assertEqual(asn.status, "Received")
		on_purchase_receipt_cancel(pr_doc, "on_cancel")

		self.assertEqual(frappe.db.get_value("ASN Item", asn.items[0].name, "received_qty"), 0)
		asn.reload()
		self.assertEqual(asn.status, "Submitted")
		later = SimpleNamespace(
			branch=PR_BRANCH,
			is_return=0,
			items=[self._receipt_row(warehouse=po.items[0].warehouse, stock_qty=1)],
		)
		self.assertEqual(len(breaches_for_purchase_receipt(later)), 1)
