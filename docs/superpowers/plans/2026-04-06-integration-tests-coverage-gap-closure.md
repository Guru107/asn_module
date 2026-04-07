# Integration Test Suite — Coverage Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ~20 new integration tests across 5 modules to raise coverage from 92.7% to ~94-95%.

**Architecture:** Create 5 new dedicated integration test files, one per module. Follow existing FrappeTestCase patterns with real documents, `integration_user_context()`, and `before_tests()`.

**Tech Stack:** Frappe Python unit tests, `frappe.tests.utils.FrappeTestCase`, `frappe.set_user()`, real ERPNext documents.

---

## Chunk 1: Purchase Return Error Tests

**Files:**
- Create: `asn_module/asn_module/handlers/tests/test_purchase_return_errors.py`

- [ ] **Step 1: Write the test file with 3 tests**

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.handlers.purchase_return import create_from_quality_inspection


class TestPurchaseReturnErrors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_purchase_receipt(self, item_code, qty, rate, company, supplier):
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": company,
				"supplier": supplier,
				"items": [
					{
						"item_code": item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": frappe.db.get_value(
							"Item Default",
							{"parent": item_code, "company": company},
							"default_warehouse",
						) or frappe.db.get_value("Warehouse", {"company": company}, "name"),
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		pr.submit()
		return pr

	def _make_quality_inspection(self, pr_name, item_code, status, purchase_receipt_item=None):
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr_name,
				"item_code": item_code,
				"sample_size": 1,
				"status": status,
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
			}
		)
		if purchase_receipt_item:
			qi.purchase_receipt_item = purchase_receipt_item
		qi.insert(ignore_permissions=True)
		qi.submit()
		return qi

	def _make_item(self, item_code):
		if not frappe.db.exists("Item", item_code):
			item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
			uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": item_code,
					"item_group": item_group,
					"stock_uom": uom,
				}
			).insert(ignore_permissions=True)

	def test_qi_item_found_in_pr_returns_that_item(self):
		"""QI with purchase_receipt_item set directly finds that row — L32-35."""
		item_code = "_Test PR Err Item A"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		pr = self._make_purchase_receipt(
			item_code=item_code,
			qty=10,
			rate=po.items[0].rate,
			company=po.company,
			supplier=po.supplier,
		)
		qi_pr_item_name = pr.items[0].name
		qi = self._make_quality_inspection(pr.name, item_code, "Rejected", qi_pr_item_name)

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={},
		)
		self.assertEqual(result["doctype"], "Purchase Receipt")
		ret = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(ret.is_return, 1)
		self.assertEqual(ret.return_against, pr.name)

	def test_qi_item_not_found_in_pr_raises(self):
		"""QI with purchase_receipt_item set to non-existent PR item row — L50."""
		item_code = "_Test PR Err Item B"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		pr = self._make_purchase_receipt(
			item_code=item_code,
			qty=10,
			rate=po.items[0].rate,
			company=po.company,
			supplier=po.supplier,
		)
		qi = self._make_quality_inspection(pr.name, item_code, "Rejected")
		frappe.db.set_value("Quality Inspection", qi.name, "purchase_receipt_item", "NONEXISTENT-ITEM-ROW")

		with self.assertRaises(frappe.ValidationError) as ctx:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={},
			)
		self.assertIn("not found", str(ctx.exception))

	def test_ambiguous_qi_raises_validation_error(self):
		"""QI without purchase_receipt_item matches multiple PR rows by item_code — L41-47."""
		item_code = "_Test PR Err Item C"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": po.company,
				"supplier": po.supplier,
				"items": [
					{
						"item_code": item_code,
						"qty": 5,
						"rate": po.items[0].rate,
						"warehouse": po.items[0].warehouse,
					},
					{
						"item_code": item_code,
						"qty": 5,
						"rate": po.items[0].rate,
						"warehouse": po.items[0].warehouse,
					},
				],
			}
		)
		pr.insert(ignore_permissions=True)
		pr.submit()
		qi = self._make_quality_inspection(pr.name, item_code, "Rejected")

		with self.assertRaises(frappe.ValidationError) as ctx:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={},
			)
		self.assertIn("Multiple", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_return_errors --lightmode`

Expected: 3 tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/asn_module/handlers/tests/test_purchase_return_errors.py
git commit -m "test(handlers): add purchase_return error branch integration tests"
```

---

## Chunk 2: Stock Transfer Error Tests

**Files:**
- Create: `asn_module/asn_module/handlers/tests/test_stock_transfer_errors.py`

- [ ] **Step 1: Write the test file with 3 tests**

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.handlers.stock_transfer import create_from_quality_inspection


class TestStockTransferErrors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()

	def _make_item(self, item_code):
		if not frappe.db.exists("Item", item_code):
			item_group = frappe.db.get_value("Item Group", {}, "name") or "All Item Groups"
			uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": item_code,
					"item_group": item_group,
					"stock_uom": uom,
					"inspection_required_before_purchase": 1,
				}
			).insert(ignore_permissions=True)

	def _make_purchase_receipt_with_qi_accepted(self, item_code):
		item_code = "_Test ST Err Item"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		company = po.company
		warehouse = po.items[0].warehouse

		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": po.supplier,
				"company": company,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": po.items[0].rate,
						"warehouse": warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)

		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr.name,
				"item_code": item_code,
				"sample_size": 4,
				"status": "Accepted",
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
			}
		)
		qi.insert(ignore_permissions=True)
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			qi.submit()
		pr.reload()
		pr.items[0].quality_inspection = qi.name
		pr.save(ignore_permissions=True)
		pr.submit()
		return pr, qi

	def test_qi_item_found_in_pr_returns_that_item(self):
		"""QI with purchase_receipt_item set directly finds that row — L30-33."""
		item_code = "_Test ST Err Item D"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": po.supplier,
				"company": po.company,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": po.items[0].rate,
						"warehouse": po.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		qi_pr_item_name = pr.items[0].name
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr.name,
				"item_code": item_code,
				"sample_size": 4,
				"status": "Accepted",
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
				"purchase_receipt_item": qi_pr_item_name,
			}
		)
		qi.insert(ignore_permissions=True)
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			qi.submit()
		pr.reload()
		pr.items[0].quality_inspection = qi.name
		pr.save(ignore_permissions=True)
		pr.submit()

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_stock_transfer"},
		)
		self.assertEqual(result["doctype"], "Stock Entry")
		se = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(se.stock_entry_type, "Material Transfer")

	def test_qi_item_not_found_in_pr_raises(self):
		"""QI with purchase_receipt_item set to non-existent PR item row — L48."""
		item_code = "_Test ST Err Item E"
		self._make_item(item_code)
		po = create_purchase_order(item_code=item_code, qty=10)
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"supplier": po.supplier,
				"company": po.company,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": po.items[0].rate,
						"warehouse": po.items[0].warehouse,
					}
				],
			}
		)
		pr.insert(ignore_permissions=True)
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr.name,
				"item_code": item_code,
				"sample_size": 4,
				"status": "Accepted",
				"inspected_by": frappe.session.user,
				"manual_inspection": 1,
				"purchase_receipt_item": "NONEXISTENT-ST-ROW",
			}
		)
		qi.insert(ignore_permissions=True)
		with (
			patch("asn_module.qr_engine.generate.generate_qr", return_value={"image_base64": "ZmFrZS1xcg=="}),
			patch("asn_module.handlers.quality_inspection._attach_qr_to_doc"),
			patch("asn_module.handlers.quality_inspection.frappe.msgprint"),
		):
			qi.submit()
		pr.reload()
		pr.items[0].quality_inspection = qi.name
		pr.save(ignore_permissions=True)
		pr.submit()

		with self.assertRaises(frappe.ValidationError) as ctx:
			create_from_quality_inspection(
				source_doctype="Quality Inspection",
				source_name=qi.name,
				payload={"action": "create_stock_transfer"},
			)
		self.assertIn("not found", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_stock_transfer_errors --lightmode`

Expected: 2 tests pass (the success path may need warehouse setup)

- [ ] **Step 3: Fix any failures and re-run**

If warehouse setup fails, add `Item Default` for the test item with a default warehouse.

- [ ] **Step 4: Commit**

```bash
git add asn_module/asn_module/handlers/tests/test_stock_transfer_errors.py
git commit -m "test(handlers): add stock_transfer error branch integration tests"
```

---

## Chunk 3: Dispatch Error Tests

**Files:**
- Create: `asn_module/asn_module/qr_engine/tests/test_dispatch_errors.py`

- [ ] **Step 1: Write the test file with 4 tests**

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order, make_test_asn
from asn_module.qr_engine.dispatch import dispatch
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions
from asn_module.tests.integration.fixtures import ensure_integration_user, integration_user_context


class TestDispatchErrors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		register_actions()
		ensure_integration_user()

	def _make_submitted_asn(self):
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		asn.submit()
		return asn

	def test_handler_returning_string_raises_validation_error(self):
		"""Handler returns string instead of dict — L65."""
		asn = self._make_submitted_asn()
		with integration_user_context():
			code = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		bad_handler = "asn_module.handlers.purchase_receipt.create_from_quality_inspection"
		original = "asn_module.handlers.purchase_receipt.create_purchase_receipt"
		with patch("asn_module.qr_engine.dispatch._get_handler_for_scan_code", return_value=(bad_handler, "ASN", asn.name, {})):
			with self.assertRaises(frappe.ValidationError) as ctx:
				dispatch(code=code)
		self.assertIn("expected a dict", str(ctx.exception))

	def test_handler_returning_error_dict_swallows_exception(self):
		"""Handler returns error dict — L80-81."""
		from asn_module.tests.integration.dispatch_flow import run_asn_pr_submitted_via_dispatch
		out = run_asn_pr_submitted_via_dispatch(
			supplier_invoice_no="ERR-DISP-" + frappe.generate_hash(length=6),
			qty=2,
		)
		with integration_user_context():
			code = get_or_create_scan_code("create_purchase_receipt", "Purchase Receipt", out.pr.name)
			# Patch the handler to return error dict
			with patch("asn_module.handlers.purchase_receipt.create_purchase_receipt", return_value={"success": False, "error": "test error"}):
				result = dispatch(code=code)
		self.assertFalse(result.get("success"))

	def test_dispatch_missing_scan_code_raises(self):
		"""dispatch() with no code raises ScanCodeNotFoundError — L157."""
		with self.assertRaises(Exception) as ctx:
			dispatch(code=None)
		self.assertIn("Missing", str(ctx.exception))

	def test_dispatch_unknown_scan_code_raises(self):
		"""dispatch() with non-existent scan code raises — L161."""
		unknown_code = "ASNLONGCODENOTEXIST1234"
		with self.assertRaises(Exception) as ctx:
			dispatch(code=unknown_code)
		self.assertIn("Unknown", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch_errors --lightmode`

Expected: 4 tests pass

- [ ] **Step 3: Fix any failures**

If the handler-patching approach doesn't work, use `patch.object` on the specific handler module function.

- [ ] **Step 4: Commit**

```bash
git add asn_module/asn_module/qr_engine/tests/test_dispatch_errors.py
git commit -m "test(qr_engine): add dispatch error path integration tests"
```

---

## Chunk 4: ASN New Services Integration Tests

**Files:**
- Create: `asn_module/asn_module/templates/pages/tests/test_asn_new_services_integration.py`

- [ ] **Step 1: Write the test file with 5 tests**

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order
from asn_module.templates.pages.asn_new_services import (
	PortalValidationError,
	ParsedBulkRow,
	ParsedSingleRow,
	enforce_bulk_limits,
	fetch_purchase_order_items,
	validate_invoice_group_consistency,
	validate_no_duplicate_po_sr_no,
	validate_qty_within_remaining,
)


class TestAsnNewServicesIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		cls._supplier = "Test Supplier SVCS-" + frappe.generate_hash(length=6)
		if not frappe.db.exists("Supplier", cls._supplier):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": cls._supplier,
					"supplier_group": frappe.db.get_value("Supplier Group", {}, "name") or "All Supplier Groups",
				}
			).insert(ignore_permissions=True)

	def test_fetch_purchase_order_items_empty_list_returns_empty(self):
		"""Empty purchase_orders list returns empty dicts — L214-215."""
		rows_by_key, remaining = fetch_purchase_order_items([])
		self.assertEqual(rows_by_key, {})
		self.assertEqual(remaining, {})

	def test_fetch_purchase_order_items_returns_grouped_rows_and_remaining_qty(self):
		"""fetch_purchase_order_items groups by (parent, sr_no) and computes remaining qty — L217-235."""
		po = create_purchase_order(qty=20)
		frappe.db.set_value("Purchase Order", po.name, "supplier", self._supplier)
		po.reload()
		rows_by_key, remaining = fetch_purchase_order_items([po.name])
		self.assertIn((po.name, str(po.items[0].idx)), rows_by_key)
		self.assertIn(po.items[0].name, remaining)

	def test_validate_qty_within_remaining_raises_on_excess(self):
		"""qty exceeds remaining → PortalValidationError at L303."""
		po = create_purchase_order(qty=10)
		row = ParsedSingleRow(
			idx=1,
			row_number=1,
			purchase_order=po.name,
			purchase_order_item=po.items[0].name,
			item_code=po.items[0].item_code,
			qty=999,
			rate=100,
			amount=99900,
		)
		with self.assertRaises(PortalValidationError):
			validate_qty_within_remaining(row, remaining_qty_by_item={po.items[0].name: 5.0})

	def test_validate_invoice_group_consistency_raises_on_mismatch(self):
		"""Items with same invoice no but different rates → error at L382."""
		rows = [
			ParsedBulkRow(
				idx=1,
				row_number=1,
				invoice_no="INV-MISMATCH",
				purchase_order="PO-MISMATCH",
				purchase_order_item="POITEM-1",
				item_code="_Test Item",
				qty=1,
				rate=100,
			),
			ParsedBulkRow(
				idx=2,
				row_number=2,
				invoice_no="INV-MISMATCH",
				purchase_order="PO-MISMATCH",
				purchase_order_item="POITEM-2",
				item_code="_Test Item",
				qty=1,
				rate=200,
			),
		]
		with self.assertRaises(PortalValidationError):
			validate_invoice_group_consistency("INV-MISMATCH", rows)

	def test_validate_no_duplicate_po_sr_no_raises_on_duplicate(self):
		"""Same PO with same sr_no appears twice → error at L404."""
		rows = [
			ParsedBulkRow(
				idx=1,
				row_number=1,
				invoice_no="INV-DUP",
				purchase_order="PO-DUP",
				purchase_order_item="POITEM-1",
				item_code="_Test Item",
				qty=1,
				rate=100,
			),
			ParsedBulkRow(
				idx=1,
				row_number=2,
				invoice_no="INV-DUP",
				purchase_order="PO-DUP",
				purchase_order_item="POITEM-2",
				item_code="_Test Item",
				qty=1,
				rate=100,
			),
		]
		with self.assertRaises(PortalValidationError):
			validate_no_duplicate_po_sr_no(rows, invoice_no="INV-DUP")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.templates.pages.tests.test_asn_new_services_integration --lightmode`

Expected: 5 tests pass

- [ ] **Step 3: Fix any failures**

If `ParsedBulkRow` or `ParsedSingleRow` need constructor args, check the class definitions.

- [ ] **Step 4: Commit**

```bash
git add asn_module/asn_module/templates/pages/tests/test_asn_new_services_integration.py
git commit -m "test(pages): add asn_new_services helper integration tests"
```

---

## Chunk 5: Transition Trace Filter Tests

**Files:**
- Create: `asn_module/asn_module/report/tests/test_transition_trace_filters.py`

- [ ] **Step 1: Write the test file with 5 tests**

```python
from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.doctype.asn.test_asn import before_tests, create_purchase_order, make_test_asn
from asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.traceability import emit_asn_item_transition


class TestTransitionTraceFilters(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		before_tests()
		super().setUpClass()
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		cls._asn = asn
		cls._asn_item = asn.items[0].name
		cls._item_code = asn.items[0].item_code

	def _emit(self, **kwargs):
		defaults = dict(
			asn=self._asn.name,
			asn_item=self._asn_item,
			item_code=self._item_code,
			ref_doctype="ASN",
			ref_name=self._asn.name,
		)
		defaults.update(kwargs)
		return emit_asn_item_transition(**defaults)

	def test_execute_filters_by_ref_doctype(self):
		"""Emit transitions with different ref_doctypes, filter by one — L43."""
		self._emit(state="Received", ref_doctype="ASN", ref_name=self._asn.name)
		self._emit(state="Submitted", ref_doctype="Purchase Receipt", ref_name="PR-FILTER-TEST")
		_, rows = execute({"ref_doctype": "ASN"})
		for row in rows:
			self.assertEqual(row[1], "ASN")

	def test_execute_filters_by_ref_name(self):
		"""Emit two transitions with different ref_names, filter by one — L45."""
		self._emit(state="Received", ref_doctype="ASN", ref_name=self._asn.name)
		self._emit(state="Submitted", ref_doctype="ASN", ref_name="RN-FILTER-TEST")
		_, rows = execute({"ref_name": self._asn.name})
		for row in rows:
			self.assertEqual(row[2], self._asn.name)

	def test_execute_filters_by_date_range_excludes_outside(self):
		"""Emit transition now, filter with past/future date range — L47, L49."""
		self._emit(state="Received")
		future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
		past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
		_, rows = execute({"from_date": future, "to_date": "2099-01-01"})
		self.assertEqual(len(rows), 0)

	def test_execute_filters_by_error_status_only(self):
		"""Emit OK and Error transitions, filter by Error only — L51."""
		self._emit(state="Received", transition_status="OK")
		self._emit(state="Submitted", transition_status="Error", ref_doctype="ASN", ref_name=self._asn.name)
		_, rows = execute({"transition_status": "Error"})
		for row in rows:
			self.assertIn("Error", str(row))

	def test_execute_filters_by_search_text_partial_match(self):
		"""Transition ref_name contains 'ABC-123', search 'BC-1' matches — L53-61."""
		self._emit(state="Received", ref_name="ASN-FILTER-BC123")
		_, rows = execute({"search": "BC-1"})
		self.assertGreater(len(rows), 0)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.report.tests.test_transition_trace_filters --lightmode`

Expected: 5 tests pass

- [ ] **Step 3: Fix any failures and re-run**

- [ ] **Step 4: Commit**

```bash
git add asn_module/asn_module/report/tests/test_transition_trace_filters.py
git commit -m "test(report): add transition trace filter integration tests"
```

---

## Chunk 6: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --lightmode`

Expected: All tests pass (old + new)

- [ ] **Step 2: Run coverage to measure delta**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate && bench --site frappe16.localhost run-tests --app asn_module --coverage --lightmode 2>&1 | tail -5`

- [ ] **Step 3: Parse coverage report**

Run:
```bash
python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('/Users/gurudattkulkarni/Workspace/bench16/sites/coverage.xml')
root = tree.getroot()
print(f'Total: {root.get(\"lines-covered\")}/{root.get(\"lines-valid\")} ({float(root.get(\"line-rate\"))*100:.1f}%)')
"
```

Expected: ~94-95%

- [ ] **Step 4: Commit remaining changes**

```bash
git add -A
git commit -m "test: add integration tests for coverage gap closure"
```
