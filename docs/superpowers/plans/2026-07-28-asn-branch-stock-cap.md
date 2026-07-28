# ASN Branch-Wise Stock Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse an ASN submission, and a Purchase Receipt submission, when the stock it will land pushes an item above `Item.custom_max_stock` for the destination branch.

**Architecture:** A new `asn_module/stock_cap/` package splits the rule into a pure decision function and the database reads that feed it. `collect_lines` normalises any source document into stock-UOM lines, `fetch_cap_context` runs the reads, and `evaluate` decides with no database access at all. Enforcement surfaces (ASN controller, Purchase Receipt hook, portal, bulk upload) are thin callers.

**Tech Stack:** Frappe v15/v16, ERPNext, Python 3.10+, `frappe.qb` query builder, `FrappeTestCase`, Hypothesis, Cypress.

**Spec:** [2026-07-28-asn-branch-stock-cap-design.md](../specs/2026-07-28-asn-branch-stock-cap-design.md)
**Glossary:** [CONTEXT.md](../../../CONTEXT.md)
**ADR:** [0001-stock-cap-is-advisory-not-transactional.md](../../adr/0001-stock-cap-is-advisory-not-transactional.md)

## Global Constraints

- Python style: **tab indentation**, double quotes, 110 char line length (`ruff`, config in `pyproject.toml`).
- Must run on both Frappe/ERPNext v15 (`development.localhost`) and v16 (`frappe16.localhost`).
- All user-visible strings wrapped in `_()`.
- Every `frappe.call()` in JS needs an `error:` callback.
- Test naming: `test_<what>_<expected_outcome>`.
- Coverage must not drop below **96%**.
- Fail open everywhere: a missing column, missing settings, or a zero/null cap silently skips the check. Never raise because configuration is absent.
- Comparison is **strictly greater**: `projected == cap` is allowed.
- Quantities compared against `Bin.actual_qty` and `Item.custom_max_stock` are always in **stock UOM**.
- The cap is **advisory, not transactional**. No locking. Do not add `FOR UPDATE`.
- Never disclose On Hand, In Transit, or Maximum Stock to users without `read` permission on `Item`.

## Environment Prerequisites

Already applied to both benches on 2026-07-28. Verify before starting:

```bash
cd /root/workspace/bench16/sites && ../env/bin/python -c "
import frappe; frappe.init(site='frappe16.localhost', sites_path='.'); frappe.connect()
for dt in ['Purchase Order','Purchase Receipt']: print(dt, frappe.db.has_column(dt,'branch'))
print('Item.custom_max_stock', frappe.db.has_column('Item','custom_max_stock'))"
```

Expected: all `True`.

## File Structure

**Create:**

| File | Responsibility |
| --- | --- |
| `asn_module/stock_cap/__init__.py` | Public re-exports only |
| `asn_module/stock_cap/models.py` | `Line`, `CapContext`, `Breach` dataclasses. No logic beyond `allowed_qty`. |
| `asn_module/stock_cap/evaluate.py` | Pure decision function. No `frappe` import. |
| `asn_module/stock_cap/collect.py` | Normalise ASN doc / ASN payload / Purchase Receipt into stock-UOM `Line`s |
| `asn_module/stock_cap/fetch.py` | The four context queries plus `has_column` guards |
| `asn_module/stock_cap/messages.py` | Desk vs portal message formatting and redaction |
| `asn_module/stock_cap/api.py` | Whitelisted `get_stock_cap_preview`, plus helpers used by enforcement surfaces |
| `asn_module/asn_module/doctype/asn_stock_cap_settings/` | Per-branch settings doctype + controller |
| `asn_module/asn_module/doctype/asn_stock_cap_warehouse/` | Child table row |
| `asn_module/tests/test_stock_cap_evaluate.py` | Pure branch matrix, no fixtures |
| `asn_module/tests/test_stock_cap_collect.py` | UOM conversion and source normalisation |
| `asn_module/tests/test_stock_cap_fetch.py` | Query behaviour against real records |
| `asn_module/tests/test_stock_cap_messages.py` | Message formatting and redaction |
| `asn_module/tests/test_stock_cap_settings.py` | Settings validation |
| `asn_module/property_tests/test_stock_cap_properties.py` | Monotonicity and breach-iff properties |
| `cypress/integration/nightly/stock_cap_e2e.js` | Desk happy path, block path, warning path |

**Modify:**

| File | Change |
| --- | --- |
| `asn_module/asn_module/doctype/asn/asn.py` | Add `_warn_stock_cap()` to `validate()`, add `before_submit()` |
| `asn_module/handlers/purchase_receipt.py` | Add `on_purchase_receipt_before_submit()` |
| `asn_module/hooks.py:159-163` | Register the Purchase Receipt `before_submit` event |
| `asn_module/templates/pages/asn_new_services.py` | Cap check in the bulk validation phase; wrap portal submit |
| `asn_module/utils/cypress_helpers.py` | Add `seed_stock_cap_context` |

**Deviation from the spec:** the spec names a single `asn_module/stock_cap.py`. The responsibilities total roughly 500 lines across five genuinely distinct concerns (data shapes, pure logic, database reads, normalisation, presentation), so this plan uses a package. Behaviour and the six-query budget are unchanged.

---

### Task 1: Settings doctypes and validation

**Files:**
- Create: `asn_module/asn_module/doctype/asn_stock_cap_warehouse/__init__.py`
- Create: `asn_module/asn_module/doctype/asn_stock_cap_warehouse/asn_stock_cap_warehouse.json`
- Create: `asn_module/asn_module/doctype/asn_stock_cap_warehouse/asn_stock_cap_warehouse.py`
- Create: `asn_module/asn_module/doctype/asn_stock_cap_settings/__init__.py`
- Create: `asn_module/asn_module/doctype/asn_stock_cap_settings/asn_stock_cap_settings.json`
- Create: `asn_module/asn_module/doctype/asn_stock_cap_settings/asn_stock_cap_settings.py`
- Test: `asn_module/tests/test_stock_cap_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: DocType `ASN Stock Cap Settings` (name = branch; fields `branch`, `enabled`, `warehouses`) and child DocType `ASN Stock Cap Warehouse` (field `warehouse`). Later tasks query both by name.

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_stock_cap_settings.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

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


class TestStockCapSettings(FrappeTestCase):
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_settings
```

Expected: FAIL with `DocType ASN Stock Cap Settings not found`.

- [ ] **Step 3: Create the child doctype**

`asn_module/asn_module/doctype/asn_stock_cap_warehouse/__init__.py` — empty file.

`asn_module/asn_module/doctype/asn_stock_cap_warehouse/asn_stock_cap_warehouse.json`:

```json
{
 "actions": [],
 "creation": "2026-07-28 00:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": ["warehouse"],
 "fields": [
  {
   "fieldname": "warehouse",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Warehouse",
   "options": "Warehouse",
   "reqd": 1
  }
 ],
 "index_web_pages_for_search": 1,
 "istable": 1,
 "links": [],
 "modified": "2026-07-28 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "ASN Module",
 "name": "ASN Stock Cap Warehouse",
 "owner": "Administrator",
 "permissions": [],
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": []
}
```

`asn_module/asn_module/doctype/asn_stock_cap_warehouse/asn_stock_cap_warehouse.py`:

```python
from frappe.model.document import Document


class ASNStockCapWarehouse(Document):
	pass
```

- [ ] **Step 4: Create the parent doctype**

`asn_module/asn_module/doctype/asn_stock_cap_settings/__init__.py` — empty file.

`asn_module/asn_module/doctype/asn_stock_cap_settings/asn_stock_cap_settings.json`:

```json
{
 "actions": [],
 "autoname": "field:branch",
 "creation": "2026-07-28 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["branch", "enabled", "warehouses_section", "warehouses"],
 "fields": [
  {
   "fieldname": "branch",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Branch",
   "options": "Branch",
   "reqd": 1,
   "unique": 1
  },
  {
   "default": "1",
   "fieldname": "enabled",
   "fieldtype": "Check",
   "in_list_view": 1,
   "label": "Enabled"
  },
  {
   "fieldname": "warehouses_section",
   "fieldtype": "Section Break",
   "label": "Cap Warehouses"
  },
  {
   "description": "Stock across these warehouses counts toward this branch's maximum. Leaf warehouses only.",
   "fieldname": "warehouses",
   "fieldtype": "Table",
   "label": "Warehouses",
   "options": "ASN Stock Cap Warehouse"
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-07-28 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "ASN Module",
 "name": "ASN Stock Cap Settings",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  },
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Stock Manager",
   "share": 1,
   "write": 1
  },
  {"read": 1, "report": 1, "role": "Stock User"}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

- [ ] **Step 5: Write the controller**

`asn_module/asn_module/doctype/asn_stock_cap_settings/asn_stock_cap_settings.py`:

```python
import frappe
from frappe import _
from frappe.model.document import Document


class ASNStockCapSettings(Document):
	def validate(self):
		self._validate_leaf_warehouses()
		self._validate_no_duplicates()
		self._validate_not_claimed_by_another_branch()

	def _validate_leaf_warehouses(self):
		for row in self.warehouses or []:
			if not frappe.db.get_value("Warehouse", row.warehouse, "is_group"):
				continue

			frappe.throw(
				_(
					"Row {0}: {1} is a group warehouse. Stock is only recorded against leaf "
					"warehouses, so a group would never count toward the cap. List its leaves instead."
				).format(row.idx, row.warehouse)
			)

	def _validate_no_duplicates(self):
		seen = set()
		for row in self.warehouses or []:
			if row.warehouse not in seen:
				seen.add(row.warehouse)
				continue

			frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, row.warehouse))

	def _validate_not_claimed_by_another_branch(self):
		warehouses = [row.warehouse for row in self.warehouses or []]
		if not warehouses:
			return

		filters = {"warehouse": ["in", warehouses], "parenttype": "ASN Stock Cap Settings"}
		if self.name:
			filters["parent"] = ["!=", self.name]

		claimed = frappe.get_all(
			"ASN Stock Cap Warehouse", filters=filters, fields=["parent", "warehouse"], limit=1
		)
		if not claimed:
			return

		frappe.throw(
			_(
				"Warehouse {0} is already a cap warehouse for branch {1}. "
				"A warehouse can belong to only one branch."
			).format(claimed[0].warehouse, claimed[0].parent)
		)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_settings
```

Expected: 4 tests PASS.

- [ ] **Step 7: Verify on v15**

```bash
bench --site development.localhost run-tests --module asn_module.tests.test_stock_cap_settings
```

Expected: 4 tests PASS.

- [ ] **Step 8: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/asn_module/doctype/asn_stock_cap_settings asn_module/asn_module/doctype/asn_stock_cap_warehouse asn_module/tests/test_stock_cap_settings.py
git commit -m "feat: add per-branch ASN Stock Cap Settings doctype"
```

---

### Task 2: Data shapes and the pure evaluator

**Files:**
- Create: `asn_module/stock_cap/__init__.py`
- Create: `asn_module/stock_cap/models.py`
- Create: `asn_module/stock_cap/evaluate.py`
- Test: `asn_module/tests/test_stock_cap_evaluate.py`

**Interfaces:**
- Consumes: nothing. This task must not import `frappe`.
- Produces:
  - `Line(branch: str, item_code: str, warehouse: str, stock_qty: float, row_idx: int)` — frozen dataclass.
  - `CapContext(cap_warehouses: dict[str, frozenset[str]], max_stock: dict[str, float], on_hand: dict[tuple[str, str], float], in_transit: dict[tuple[str, str], float])` — frozen dataclass.
  - `Breach(branch, item_code, row_idxs: tuple[int, ...], on_hand, in_transit, incoming, projected, cap)` with property `allowed_qty: float`.
  - `evaluate(lines: list[Line], context: CapContext, consumed: dict[tuple[str, str], float] | None = None) -> list[Breach]`.

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_stock_cap_evaluate.py`:

```python
import unittest

from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import CapContext, Line

BRANCH = "Mumbai"
ITEM = "WIDGET"
WH = "Main - MC"


def _context(**overrides) -> CapContext:
	defaults = {
		"cap_warehouses": {BRANCH: frozenset({WH})},
		"max_stock": {ITEM: 100.0},
		"on_hand": {},
		"in_transit": {},
	}
	defaults.update(overrides)
	return CapContext(**defaults)


def _line(qty: float, idx: int = 1, warehouse: str = WH, branch: str = BRANCH) -> Line:
	return Line(branch=branch, item_code=ITEM, warehouse=warehouse, stock_qty=qty, row_idx=idx)


class TestStockCapEvaluate(unittest.TestCase):
	def test_no_cap_configured_produces_no_breach(self):
		self.assertEqual(evaluate([_line(500)], _context(max_stock={})), [])

	def test_zero_cap_is_treated_as_uncapped(self):
		self.assertEqual(evaluate([_line(500)], _context(max_stock={ITEM: 0.0})), [])

	def test_under_cap_produces_no_breach(self):
		self.assertEqual(evaluate([_line(50)], _context(on_hand={(BRANCH, ITEM): 20.0})), [])

	def test_exactly_at_cap_is_allowed(self):
		self.assertEqual(evaluate([_line(80)], _context(on_hand={(BRANCH, ITEM): 20.0})), [])

	def test_incoming_alone_breaches_cap(self):
		breaches = evaluate([_line(101)], _context())
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].projected, 101.0)
		self.assertEqual(breaches[0].cap, 100.0)

	def test_breach_only_once_in_transit_counted(self):
		context = _context(on_hand={(BRANCH, ITEM): 50.0}, in_transit={(BRANCH, ITEM): 40.0})
		self.assertEqual(evaluate([_line(10)], context), [])
		breaches = evaluate([_line(11)], context)
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].in_transit, 40.0)

	def test_breach_only_once_consumed_headroom_applied(self):
		context = _context(on_hand={(BRANCH, ITEM): 90.0})
		self.assertEqual(evaluate([_line(10)], context), [])
		breaches = evaluate([_line(10)], context, consumed={(BRANCH, ITEM): 5.0})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].projected, 105.0)

	def test_warehouse_outside_cap_warehouses_is_ignored(self):
		self.assertEqual(evaluate([_line(500, warehouse="Other - MC")], _context()), [])

	def test_branch_without_settings_is_ignored(self):
		self.assertEqual(evaluate([_line(500, branch="Delhi")], _context()), [])

	def test_multiple_lines_for_same_item_are_summed(self):
		breaches = evaluate([_line(60, idx=1), _line(50, idx=2)], _context())
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].incoming, 110.0)
		self.assertEqual(breaches[0].row_idxs, (1, 2))

	def test_allowed_qty_is_remaining_headroom(self):
		breaches = evaluate([_line(30)], _context(on_hand={(BRANCH, ITEM): 80.0}))
		self.assertEqual(breaches[0].allowed_qty, 20.0)

	def test_allowed_qty_is_zero_when_already_over_cap(self):
		breaches = evaluate([_line(5)], _context(on_hand={(BRANCH, ITEM): 200.0}))
		self.assertEqual(breaches[0].allowed_qty, 0.0)

	def test_breaches_are_sorted_deterministically(self):
		context = CapContext(
			cap_warehouses={BRANCH: frozenset({WH})},
			max_stock={"B_ITEM": 1.0, "A_ITEM": 1.0},
			on_hand={},
			in_transit={},
		)
		lines = [
			Line(branch=BRANCH, item_code="B_ITEM", warehouse=WH, stock_qty=5, row_idx=1),
			Line(branch=BRANCH, item_code="A_ITEM", warehouse=WH, stock_qty=5, row_idx=2),
		]
		self.assertEqual([b.item_code for b in evaluate(lines, context)], ["A_ITEM", "B_ITEM"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_evaluate
```

Expected: FAIL with `ModuleNotFoundError: No module named 'asn_module.stock_cap'`.

- [ ] **Step 3: Write the models**

`asn_module/stock_cap/__init__.py`:

```python
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import Breach, CapContext, Line

__all__ = ["Breach", "CapContext", "Line", "evaluate"]
```

`asn_module/stock_cap/models.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
	"""One quantity landing in one warehouse, already converted to stock UOM."""

	branch: str
	item_code: str
	warehouse: str
	stock_qty: float
	row_idx: int


@dataclass(frozen=True)
class CapContext:
	"""Everything the evaluator needs, as plain data. Built by fetch_cap_context."""

	cap_warehouses: dict[str, frozenset[str]]
	max_stock: dict[str, float]
	on_hand: dict[tuple[str, str], float]
	in_transit: dict[tuple[str, str], float]


@dataclass(frozen=True)
class Breach:
	branch: str
	item_code: str
	row_idxs: tuple[int, ...]
	on_hand: float
	in_transit: float
	incoming: float
	projected: float
	cap: float

	@property
	def allowed_qty(self) -> float:
		"""Largest additional quantity that would not breach. The only figure suppliers may see."""
		return max(self.cap - (self.projected - self.incoming), 0.0)
```

- [ ] **Step 4: Write the evaluator**

`asn_module/stock_cap/evaluate.py`:

```python
from asn_module.stock_cap.models import Breach, CapContext, Line


def _as_float(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def evaluate(
	lines: list[Line],
	context: CapContext,
	consumed: dict[tuple[str, str], float] | None = None,
) -> list[Breach]:
	"""Decide which (branch, item) groups exceed their maximum.

	Pure: no database access and no frappe imports, so the whole branch matrix is
	testable without stock ledger fixtures. Every skip here is a documented
	fail-open rule from the spec.
	"""
	consumed = consumed or {}
	grouped: dict[tuple[str, str], list[Line]] = {}

	for line in lines:
		cap_warehouses = context.cap_warehouses.get(line.branch)
		if not cap_warehouses or line.warehouse not in cap_warehouses:
			continue
		if _as_float(context.max_stock.get(line.item_code)) <= 0:
			continue

		grouped.setdefault((line.branch, line.item_code), []).append(line)

	breaches = []
	for (branch, item_code), group in grouped.items():
		cap = _as_float(context.max_stock.get(item_code))
		on_hand = _as_float(context.on_hand.get((branch, item_code)))
		in_transit = _as_float(context.in_transit.get((branch, item_code)))
		incoming = sum(_as_float(line.stock_qty) for line in group)
		projected = on_hand + in_transit + incoming + _as_float(consumed.get((branch, item_code)))

		if projected <= cap:
			continue

		breaches.append(
			Breach(
				branch=branch,
				item_code=item_code,
				row_idxs=tuple(sorted(line.row_idx for line in group)),
				on_hand=on_hand,
				in_transit=in_transit,
				incoming=incoming,
				projected=projected,
				cap=cap,
			)
		)

	return sorted(breaches, key=lambda breach: (breach.branch, breach.item_code))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_evaluate
```

Expected: 13 tests PASS.

- [ ] **Step 6: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap asn_module/tests/test_stock_cap_evaluate.py
git commit -m "feat: add pure stock cap evaluator"
```

---

### Task 3: Line collection and UOM conversion

**Files:**
- Create: `asn_module/stock_cap/collect.py`
- Test: `asn_module/tests/test_stock_cap_collect.py`

**Interfaces:**
- Consumes: `Line` from Task 2.
- Produces:
  - `asn_rows_from_doc(doc) -> list[dict]` — adapts a saved or unsaved ASN document to the row shape.
  - `collect_lines_from_asn_rows(rows: list[dict]) -> list[Line]` where each row has keys `idx`, `purchase_order`, `purchase_order_item`, `item_code`, `qty`. Runs two queries.
  - `collect_lines_from_purchase_receipt(doc) -> list[Line]`. Runs zero queries.

Purchase Order `branch` is read from the header only, per spec. A `conversion_factor` of 0 or `None` is treated as 1.

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_stock_cap_collect.py`:

```python
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
)
from asn_module.utils.test_setup import before_tests


def _receipt_row(**overrides):
	defaults = {
		"idx": 1,
		"item_code": "WIDGET",
		"warehouse": "Main - MC",
		"stock_qty": 30.0,
		"rejected_qty": 0.0,
		"rejected_warehouse": None,
		"conversion_factor": 1.0,
	}
	defaults.update(overrides)
	return SimpleNamespace(**defaults)


class TestStockCapCollectPurchaseReceipt(FrappeTestCase):
	def test_receipt_lines_use_stock_qty_without_conversion(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[_receipt_row(stock_qty=30.0, conversion_factor=10.0)],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].stock_qty, 30.0)
		self.assertEqual(lines[0].warehouse, "Main - MC")
		self.assertEqual(lines[0].branch, "Mumbai")

	def test_return_receipt_produces_no_lines(self):
		doc = SimpleNamespace(branch="Mumbai", is_return=1, items=[_receipt_row(stock_qty=-30.0)])
		self.assertEqual(collect_lines_from_purchase_receipt(doc), [])

	def test_rejected_qty_becomes_its_own_line_in_rejected_warehouse(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[
				_receipt_row(
					stock_qty=20.0,
					rejected_qty=3.0,
					rejected_warehouse="Quarantine - MC",
					conversion_factor=2.0,
				)
			],
		)
		lines = collect_lines_from_purchase_receipt(doc)
		self.assertEqual(len(lines), 2)
		by_warehouse = {line.warehouse: line.stock_qty for line in lines}
		self.assertEqual(by_warehouse["Main - MC"], 20.0)
		self.assertEqual(by_warehouse["Quarantine - MC"], 6.0)

	def test_rejected_qty_without_rejected_warehouse_is_dropped(self):
		doc = SimpleNamespace(
			branch="Mumbai",
			is_return=0,
			items=[_receipt_row(stock_qty=20.0, rejected_qty=3.0, rejected_warehouse=None)],
		)
		self.assertEqual(len(collect_lines_from_purchase_receipt(doc)), 1)

	def test_receipt_without_branch_produces_no_lines(self):
		doc = SimpleNamespace(branch=None, is_return=0, items=[_receipt_row()])
		self.assertEqual(collect_lines_from_purchase_receipt(doc), [])


class TestStockCapCollectASN(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()

	def test_asn_rows_from_doc_extracts_row_shape(self):
		doc = SimpleNamespace(
			items=[
				SimpleNamespace(
					idx=1,
					purchase_order="PO-0001",
					purchase_order_item="poi-1",
					item_code="WIDGET",
					qty=5.0,
				)
			]
		)
		self.assertEqual(
			asn_rows_from_doc(doc),
			[
				{
					"idx": 1,
					"purchase_order": "PO-0001",
					"purchase_order_item": "poi-1",
					"item_code": "WIDGET",
					"qty": 5.0,
				}
			],
		)

	def test_rows_without_purchase_order_are_skipped(self):
		rows = [{"idx": 1, "purchase_order": "", "purchase_order_item": "", "item_code": "X", "qty": 1}]
		self.assertEqual(collect_lines_from_asn_rows(rows), [])

	def test_missing_branch_column_returns_no_lines(self):
		rows = [
			{
				"idx": 1,
				"purchase_order": "PO-0001",
				"purchase_order_item": "poi-1",
				"item_code": "WIDGET",
				"qty": 1,
			}
		]
		original = frappe.db.has_column

		def fake_has_column(doctype, column):
			if doctype == "Purchase Order" and column == "branch":
				return False
			return original(doctype, column)

		frappe.db.has_column = fake_has_column
		try:
			self.assertEqual(collect_lines_from_asn_rows(rows), [])
		finally:
			frappe.db.has_column = original
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_collect
```

Expected: FAIL with `ModuleNotFoundError: No module named 'asn_module.stock_cap.collect'`.

- [ ] **Step 3: Write the collector**

`asn_module/stock_cap/collect.py`:

```python
import frappe
from frappe.utils import flt

from asn_module.stock_cap.models import Line


def _conversion_factor(value) -> float:
	factor = flt(value)
	return factor if factor > 0 else 1.0


def asn_rows_from_doc(doc) -> list[dict]:
	"""Adapt a saved or unsaved ASN document to the row shape collect_lines_from_asn_rows expects."""
	return [
		{
			"idx": row.idx,
			"purchase_order": row.purchase_order,
			"purchase_order_item": row.purchase_order_item,
			"item_code": row.item_code,
			"qty": flt(row.qty),
		}
		for row in (doc.items or [])
	]


def collect_lines_from_asn_rows(rows: list[dict]) -> list[Line]:
	"""Normalise ASN rows into stock-UOM lines.

	ASN quantities are in the Purchase Order line's purchase UOM, so every quantity is
	multiplied by that line's conversion factor before it can be compared with Bin.
	"""
	usable = [row for row in rows if row.get("purchase_order") and row.get("purchase_order_item")]
	if not usable:
		return []

	if not frappe.db.has_column("Purchase Order", "branch"):
		return []

	purchase_orders = sorted({row["purchase_order"] for row in usable})
	po_rows = frappe.get_all(
		"Purchase Order",
		filters={"name": ["in", purchase_orders]},
		fields=["name", "branch", "set_warehouse"],
		limit_page_length=0,
	)
	po_by_name = {row.name: row for row in po_rows}

	po_item_names = sorted({row["purchase_order_item"] for row in usable})
	po_item_rows = frappe.get_all(
		"Purchase Order Item",
		filters={"name": ["in", po_item_names]},
		fields=["name", "warehouse", "conversion_factor"],
		limit_page_length=0,
	)
	po_item_by_name = {row.name: row for row in po_item_rows}

	lines = []
	for row in usable:
		purchase_order = po_by_name.get(row["purchase_order"])
		po_item = po_item_by_name.get(row["purchase_order_item"])
		if not purchase_order or not po_item or not purchase_order.branch:
			continue

		warehouse = po_item.warehouse or purchase_order.set_warehouse
		if not warehouse:
			continue

		lines.append(
			Line(
				branch=purchase_order.branch,
				item_code=row["item_code"],
				warehouse=warehouse,
				stock_qty=flt(row["qty"]) * _conversion_factor(po_item.conversion_factor),
				row_idx=int(row.get("idx") or 0),
			)
		)

	return lines


def collect_lines_from_purchase_receipt(doc) -> list[Line]:
	"""Normalise a Purchase Receipt. Its stock_qty is already in stock UOM.

	Returns carry negative quantities and reduce stock, so they can never breach a maximum.
	Rejected quantities post to a separate warehouse and become their own line.
	"""
	if getattr(doc, "is_return", 0):
		return []

	branch = getattr(doc, "branch", None)
	if not branch:
		return []

	lines = []
	for row in doc.items or []:
		if flt(row.stock_qty) > 0 and row.warehouse:
			lines.append(
				Line(
					branch=branch,
					item_code=row.item_code,
					warehouse=row.warehouse,
					stock_qty=flt(row.stock_qty),
					row_idx=int(row.idx or 0),
				)
			)

		rejected_stock_qty = flt(row.rejected_qty) * _conversion_factor(row.conversion_factor)
		if rejected_stock_qty > 0 and row.rejected_warehouse:
			lines.append(
				Line(
					branch=branch,
					item_code=row.item_code,
					warehouse=row.rejected_warehouse,
					stock_qty=rejected_stock_qty,
					row_idx=int(row.idx or 0),
				)
			)

	return lines
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_collect
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap/collect.py asn_module/tests/test_stock_cap_collect.py
git commit -m "feat: normalise ASN and receipt lines to stock UOM"
```

---

### Task 4: Context fetching

**Files:**
- Create: `asn_module/stock_cap/fetch.py`
- Test: `asn_module/tests/test_stock_cap_fetch.py`

**Interfaces:**
- Consumes: `Line`, `CapContext` from Task 2.
- Produces: `fetch_cap_context(lines: list[Line], exclude_asn_name: str | None = None) -> CapContext`. Four queries.

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_stock_cap_fetch.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.fetch import fetch_cap_context
from asn_module.stock_cap.models import Line
from asn_module.utils.test_setup import before_tests

BRANCH = "_Test Fetch Branch"
ITEM = "_Test Fetch Item"


def _company():
	return frappe.db.get_value("Company", {}, "name")


def _warehouse(name: str) -> str:
	abbr = frappe.get_cached_value("Company", _company(), "abbr")
	full_name = f"{name} - {abbr}"
	if not frappe.db.exists("Warehouse", full_name):
		frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": name, "company": _company(), "is_group": 0}
		).insert(ignore_permissions=True)
	return full_name


class TestStockCapFetch(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()
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

	def setUp(self):
		self.warehouse = _warehouse("_Test Fetch WH")
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.db.set_value("Item", ITEM, "custom_max_stock", 100)

	def _line(self) -> Line:
		return Line(branch=BRANCH, item_code=ITEM, warehouse=self.warehouse, stock_qty=1.0, row_idx=1)

	def _make_settings(self, enabled: int = 1, warehouses: list[str] | None = None):
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": BRANCH,
				"enabled": enabled,
				"warehouses": [{"warehouse": w} for w in (warehouses or [self.warehouse])],
			}
		).insert(ignore_permissions=True)

	def test_no_settings_document_yields_no_cap_warehouses(self):
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_disabled_settings_yields_no_cap_warehouses(self):
		self._make_settings(enabled=0)
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_empty_warehouse_table_yields_no_cap_warehouses(self):
		self._make_settings(warehouses=[])
		self.assertEqual(fetch_cap_context([self._line()]).cap_warehouses, {})

	def test_enabled_settings_expose_cap_warehouses(self):
		self._make_settings()
		context = fetch_cap_context([self._line()])
		self.assertEqual(context.cap_warehouses, {BRANCH: frozenset({self.warehouse})})

	def test_max_stock_is_read_from_item(self):
		self._make_settings()
		self.assertEqual(fetch_cap_context([self._line()]).max_stock[ITEM], 100.0)

	def test_missing_max_stock_column_yields_empty_caps(self):
		self._make_settings()
		original = frappe.db.has_column

		def fake_has_column(doctype, column):
			if doctype == "Item" and column == "custom_max_stock":
				return False
			return original(doctype, column)

		frappe.db.has_column = fake_has_column
		try:
			self.assertEqual(fetch_cap_context([self._line()]).max_stock, {})
		finally:
			frappe.db.has_column = original

	def test_missing_bin_rows_coalesce_to_zero(self):
		self._make_settings()
		context = fetch_cap_context([self._line()])
		self.assertEqual(context.on_hand.get((BRANCH, ITEM), 0.0), 0.0)

	def test_no_lines_returns_empty_context(self):
		context = fetch_cap_context([])
		self.assertEqual(context.cap_warehouses, {})
		self.assertEqual(context.max_stock, {})
		self.assertEqual(context.on_hand, {})
		self.assertEqual(context.in_transit, {})


class TestStockCapFetchInTransit(FrappeTestCase):
	"""In-transit behaviour needs real submitted ASNs, so it lives in its own class."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()

	def setUp(self):
		from asn_module.asn_module.doctype.asn.test_asn import (
			create_purchase_order,
			make_test_asn,
		)

		self.purchase_order = create_purchase_order()
		self.po_item = self.purchase_order.items[0]
		self.branch = BRANCH
		if not frappe.db.exists("Branch", self.branch):
			frappe.get_doc({"doctype": "Branch", "branch": self.branch}).insert(
				ignore_permissions=True
			)
		frappe.db.set_value("Purchase Order", self.purchase_order.name, "branch", self.branch)

		self.warehouse = self.po_item.warehouse
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.get_doc(
			{
				"doctype": "ASN Stock Cap Settings",
				"branch": self.branch,
				"enabled": 1,
				"warehouses": [{"warehouse": self.warehouse}],
			}
		).insert(ignore_permissions=True)

		self.asn = make_test_asn(purchase_order=self.purchase_order, qty=7)
		self.asn.insert()
		self.asn.submit()

	def _line(self) -> Line:
		return Line(
			branch=self.branch,
			item_code=self.po_item.item_code,
			warehouse=self.warehouse,
			stock_qty=1.0,
			row_idx=1,
		)

	def _in_transit(self, exclude=None) -> float:
		context = fetch_cap_context([self._line()], exclude_asn_name=exclude)
		return context.in_transit.get((self.branch, self.po_item.item_code), 0.0)

	def test_submitted_asn_contributes_to_in_transit(self):
		self.assertEqual(self._in_transit(), 7.0 * (self.po_item.conversion_factor or 1))

	def test_exclude_asn_name_removes_that_asn(self):
		self.assertEqual(self._in_transit(exclude=self.asn.name), 0.0)

	def test_received_status_is_excluded(self):
		frappe.db.set_value("ASN", self.asn.name, "status", "Received", update_modified=False)
		self.assertEqual(self._in_transit(), 0.0)

	def test_closed_status_is_excluded(self):
		frappe.db.set_value("ASN", self.asn.name, "status", "Closed", update_modified=False)
		self.assertEqual(self._in_transit(), 0.0)

	def test_cancelled_asn_is_excluded(self):
		self.asn.cancel()
		self.assertEqual(self._in_transit(), 0.0)

	def test_received_qty_is_deducted_from_in_transit(self):
		frappe.db.set_value(
			"ASN Item", self.asn.items[0].name, "received_qty", 3, update_modified=False
		)
		expected = 4.0 * (self.po_item.conversion_factor or 1)
		self.assertEqual(self._in_transit(), expected)

	def test_over_received_line_clamps_to_zero_rather_than_going_negative(self):
		frappe.db.set_value(
			"ASN Item", self.asn.items[0].name, "received_qty", 99, update_modified=False
		)
		self.assertEqual(self._in_transit(), 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_fetch
```

Expected: FAIL with `ModuleNotFoundError: No module named 'asn_module.stock_cap.fetch'`.

- [ ] **Step 3: Write the fetcher**

`asn_module/stock_cap/fetch.py`:

```python
import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from asn_module.stock_cap.models import CapContext, Line

EXCLUDED_ASN_STATUSES = ("Received", "Closed")


def fetch_cap_context(lines: list[Line], exclude_asn_name: str | None = None) -> CapContext:
	"""Run every read the evaluator needs and return plain data. Makes no decisions."""
	if not lines:
		return CapContext(cap_warehouses={}, max_stock={}, on_hand={}, in_transit={})

	branches = sorted({line.branch for line in lines})
	item_codes = sorted({line.item_code for line in lines})

	cap_warehouses = _fetch_cap_warehouses(branches)
	if not cap_warehouses:
		return CapContext(cap_warehouses={}, max_stock={}, on_hand={}, in_transit={})

	branch_by_warehouse = {
		warehouse: branch
		for branch, warehouses in cap_warehouses.items()
		for warehouse in warehouses
	}
	all_warehouses = sorted(branch_by_warehouse)

	return CapContext(
		cap_warehouses=cap_warehouses,
		max_stock=_fetch_max_stock(item_codes),
		on_hand=_fetch_on_hand(item_codes, all_warehouses, branch_by_warehouse),
		in_transit=_fetch_in_transit(
			item_codes, all_warehouses, branch_by_warehouse, exclude_asn_name
		),
	)


def _fetch_cap_warehouses(branches: list[str]) -> dict[str, frozenset[str]]:
	"""Enabled settings only. A branch with an empty warehouse table simply never appears."""
	settings = DocType("ASN Stock Cap Settings")
	warehouse_row = DocType("ASN Stock Cap Warehouse")

	rows = (
		frappe.qb.from_(warehouse_row)
		.inner_join(settings)
		.on(settings.name == warehouse_row.parent)
		.select(settings.name.as_("branch"), warehouse_row.warehouse)
		.where(settings.name.isin(branches))
		.where(settings.enabled == 1)
		.where(warehouse_row.parenttype == "ASN Stock Cap Settings")
	).run(as_dict=True)

	collected: dict[str, set[str]] = {}
	for row in rows:
		if row.warehouse:
			collected.setdefault(row.branch, set()).add(row.warehouse)

	return {branch: frozenset(warehouses) for branch, warehouses in collected.items()}


def _fetch_max_stock(item_codes: list[str]) -> dict[str, float]:
	if not frappe.db.has_column("Item", "custom_max_stock"):
		return {}

	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", "custom_max_stock"],
		limit_page_length=0,
	)
	return {row.name: flt(row.custom_max_stock) for row in rows}


def _fetch_on_hand(
	item_codes: list[str], warehouses: list[str], branch_by_warehouse: dict[str, str]
) -> dict[tuple[str, str], float]:
	bin_table = DocType("Bin")
	rows = (
		frappe.qb.from_(bin_table)
		.select(bin_table.item_code, bin_table.warehouse, Sum(bin_table.actual_qty).as_("qty"))
		.where(bin_table.item_code.isin(item_codes))
		.where(bin_table.warehouse.isin(warehouses))
		.groupby(bin_table.item_code, bin_table.warehouse)
	).run(as_dict=True)

	return _aggregate_by_branch(rows, branch_by_warehouse)


def _fetch_in_transit(
	item_codes: list[str],
	warehouses: list[str],
	branch_by_warehouse: dict[str, str],
	exclude_asn_name: str | None,
) -> dict[tuple[str, str], float]:
	"""Undelivered quantity on other submitted ASNs, converted to stock UOM.

	Raw SQL rather than the query builder because GREATEST() has no portable
	query-builder equivalent, and clamping per row matters: an over-receipted line
	must not lend negative in-transit quantity to its siblings.
	"""
	item_placeholders = ", ".join(["%s"] * len(item_codes))
	warehouse_placeholders = ", ".join(["%s"] * len(warehouses))
	status_placeholders = ", ".join(["%s"] * len(EXCLUDED_ASN_STATUSES))

	exclude_clause = ""
	params: list = [*item_codes, *warehouses, *EXCLUDED_ASN_STATUSES]
	if exclude_asn_name:
		exclude_clause = "AND asn.name != %s"
		params.append(exclude_asn_name)

	rows = frappe.db.sql(
		f"""
		SELECT
			ai.item_code AS item_code,
			COALESCE(poi.warehouse, po.set_warehouse) AS warehouse,
			SUM(
				GREATEST(ai.qty - COALESCE(ai.received_qty, 0), 0)
				* CASE WHEN COALESCE(poi.conversion_factor, 0) > 0
					THEN poi.conversion_factor ELSE 1 END
			) AS qty
		FROM `tabASN Item` ai
		INNER JOIN `tabASN` asn ON asn.name = ai.parent
		INNER JOIN `tabPurchase Order Item` poi ON poi.name = ai.purchase_order_item
		INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
		WHERE ai.item_code IN ({item_placeholders})
			AND COALESCE(poi.warehouse, po.set_warehouse) IN ({warehouse_placeholders})
			AND asn.docstatus = 1
			AND asn.status NOT IN ({status_placeholders})
			{exclude_clause}
		GROUP BY ai.item_code, COALESCE(poi.warehouse, po.set_warehouse)
		""",
		params,
		as_dict=True,
	)

	return _aggregate_by_branch(rows, branch_by_warehouse)


def _aggregate_by_branch(rows, branch_by_warehouse: dict[str, str]) -> dict[tuple[str, str], float]:
	totals: dict[tuple[str, str], float] = {}
	for row in rows:
		branch = branch_by_warehouse.get(row["warehouse"])
		if not branch:
			continue

		key = (branch, row["item_code"])
		totals[key] = totals.get(key, 0.0) + flt(row["qty"])

	return totals
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_fetch
```

Expected: 15 tests PASS.

- [ ] **Step 5: Verify on v15**

```bash
bench --site development.localhost run-tests --module asn_module.tests.test_stock_cap_fetch
```

Expected: 15 tests PASS.

- [ ] **Step 6: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap/fetch.py asn_module/tests/test_stock_cap_fetch.py
git commit -m "feat: fetch stock cap context in four batched queries"
```

---

### Task 5: Messages, redaction, and the service API

**Files:**
- Create: `asn_module/stock_cap/messages.py`
- Create: `asn_module/stock_cap/api.py`
- Modify: `asn_module/stock_cap/__init__.py`
- Test: `asn_module/tests/test_stock_cap_messages.py`

**Interfaces:**
- Consumes: `Breach` (Task 2); `asn_rows_from_doc`, `collect_lines_from_asn_rows`, `collect_lines_from_purchase_receipt` (Task 3); `fetch_cap_context` (Task 4); `evaluate` (Task 2).
- Produces:
  - `may_see_stock_figures() -> bool`
  - `format_breaches(breaches: list[Breach], detailed: bool) -> str`
  - `breaches_for_asn_rows(rows, exclude_asn_name=None, consumed=None) -> list[Breach]`
  - `breaches_for_asn_doc(doc) -> list[Breach]`
  - `breaches_for_purchase_receipt(doc) -> list[Breach]`
  - `consumed_from_breach_free_rows(rows) -> dict[tuple[str, str], float]`
  - `get_stock_cap_preview(items, asn_name=None) -> list[dict]` (whitelisted)

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_stock_cap_messages.py`:

```python
from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.messages import format_breaches
from asn_module.stock_cap.models import Breach

BREACH = Breach(
	branch="Mumbai",
	item_code="WIDGET",
	row_idxs=(1, 2),
	on_hand=60.0,
	in_transit=20.0,
	incoming=40.0,
	projected=120.0,
	cap=100.0,
)


class TestStockCapMessages(FrappeTestCase):
	def test_detailed_message_includes_stock_figures(self):
		message = format_breaches([BREACH], detailed=True)
		self.assertIn("WIDGET", message)
		self.assertIn("Mumbai", message)
		self.assertIn("120", message)
		self.assertIn("100", message)
		self.assertIn("60", message)

	def test_redacted_message_hides_stock_figures(self):
		message = format_breaches([BREACH], detailed=False)
		self.assertIn("WIDGET", message)
		self.assertNotIn("Mumbai", message)
		self.assertNotIn("120", message)
		self.assertNotIn("60", message)

	def test_redacted_message_reports_allowed_qty(self):
		self.assertEqual(BREACH.allowed_qty, 20.0)
		self.assertIn("20", format_breaches([BREACH], detailed=False))

	def test_empty_breach_list_produces_empty_message(self):
		self.assertEqual(format_breaches([], detailed=True), "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_messages
```

Expected: FAIL with `ModuleNotFoundError: No module named 'asn_module.stock_cap.messages'`.

- [ ] **Step 3: Write the message formatter**

`asn_module/stock_cap/messages.py`:

```python
import frappe
from frappe import _
from frappe.utils import flt

from asn_module.stock_cap.models import Breach


def may_see_stock_figures() -> bool:
	"""Only users who can read Item may see on-hand, in-transit, and maximum figures.

	Supplier portal users cannot, so their messages carry Allowed Qty alone.
	"""
	return bool(frappe.has_permission("Item", "read"))


def _detailed(breach: Breach) -> str:
	return _(
		"Item {0} in branch {1} (rows {2}): projected stock {3} exceeds maximum {4}. "
		"On hand {5}, in transit {6}, this document {7}."
	).format(
		breach.item_code,
		breach.branch,
		", ".join(str(idx) for idx in breach.row_idxs),
		flt(breach.projected),
		flt(breach.cap),
		flt(breach.on_hand),
		flt(breach.in_transit),
		flt(breach.incoming),
	)


def _redacted(breach: Breach) -> str:
	return _("Item {0} (rows {1}): you may declare at most {2} more.").format(
		breach.item_code,
		", ".join(str(idx) for idx in breach.row_idxs),
		flt(breach.allowed_qty),
	)


def format_breaches(breaches: list[Breach], detailed: bool) -> str:
	if not breaches:
		return ""

	formatter = _detailed if detailed else _redacted
	return "\n".join(formatter(breach) for breach in breaches)
```

- [ ] **Step 4: Write the service API**

`asn_module/stock_cap/api.py`:

```python
import json

import frappe
from frappe import _
from frappe.utils import flt

from asn_module.stock_cap.collect import (
	asn_rows_from_doc,
	collect_lines_from_asn_rows,
	collect_lines_from_purchase_receipt,
)
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.fetch import fetch_cap_context
from asn_module.stock_cap.messages import may_see_stock_figures
from asn_module.stock_cap.models import Breach


def breaches_for_asn_rows(
	rows: list[dict],
	exclude_asn_name: str | None = None,
	consumed: dict[tuple[str, str], float] | None = None,
) -> list[Breach]:
	lines = collect_lines_from_asn_rows(rows)
	if not lines:
		return []

	context = fetch_cap_context(lines, exclude_asn_name=exclude_asn_name)
	return evaluate(lines, context, consumed=consumed)


def breaches_for_asn_doc(doc) -> list[Breach]:
	return breaches_for_asn_rows(asn_rows_from_doc(doc), exclude_asn_name=doc.name or None)


def breaches_for_purchase_receipt(doc) -> list[Breach]:
	"""Exclude the ASN this receipt came from.

	At before_submit that ASN is still Submitted with received_qty 0, so its quantity
	would otherwise be counted once as in-transit and again as this receipt's own.
	"""
	lines = collect_lines_from_purchase_receipt(doc)
	if not lines:
		return []

	context = fetch_cap_context(lines, exclude_asn_name=getattr(doc, "asn", None) or None)
	return evaluate(lines, context)


def consumed_from_breach_free_rows(rows: list[dict]) -> dict[tuple[str, str], float]:
	"""Headroom claimed by rows already accepted earlier in the same bulk upload."""
	consumed: dict[tuple[str, str], float] = {}
	for line in collect_lines_from_asn_rows(rows):
		key = (line.branch, line.item_code)
		consumed[key] = consumed.get(key, 0.0) + flt(line.stock_qty)

	return consumed


@frappe.whitelist()
def get_stock_cap_preview(items, asn_name: str | None = None) -> list[dict]:
	"""Headroom preview for the ASN entry form.

	Suppliers receive allowed_qty and a breach flag only; stock figures are withheld
	unless the caller can read Item.
	"""
	if isinstance(items, str):
		items = json.loads(items)

	rows = []
	for index, item in enumerate(items or [], start=1):
		purchase_order = (item.get("purchase_order") or "").strip()
		if not purchase_order:
			continue

		_assert_purchase_order_access(purchase_order)
		rows.append(
			{
				"idx": item.get("idx") or index,
				"purchase_order": purchase_order,
				"purchase_order_item": item.get("purchase_order_item"),
				"item_code": item.get("item_code"),
				"qty": flt(item.get("qty")),
			}
		)

	detailed = may_see_stock_figures()
	preview = []
	for breach in breaches_for_asn_rows(rows, exclude_asn_name=asn_name):
		entry = {
			"item_code": breach.item_code,
			"row_idxs": list(breach.row_idxs),
			"breached": True,
			"allowed_qty": flt(breach.allowed_qty),
		}
		if detailed:
			entry.update(
				{
					"branch": breach.branch,
					"on_hand": flt(breach.on_hand),
					"in_transit": flt(breach.in_transit),
					"projected": flt(breach.projected),
					"cap": flt(breach.cap),
				}
			)
		preview.append(entry)

	return preview


def _assert_purchase_order_access(purchase_order: str):
	doc = frappe.get_doc("Purchase Order", purchase_order)
	if doc.has_permission("read") or frappe.has_website_permission(
		doc, "read", user=frappe.session.user
	):
		return

	frappe.throw(
		_("Not permitted to access Purchase Order {0}").format(purchase_order),
		frappe.PermissionError,
	)
```

- [ ] **Step 5: Update the package exports**

Replace the contents of `asn_module/stock_cap/__init__.py`:

```python
from asn_module.stock_cap.api import (
	breaches_for_asn_doc,
	breaches_for_asn_rows,
	breaches_for_purchase_receipt,
	consumed_from_breach_free_rows,
	get_stock_cap_preview,
)
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures
from asn_module.stock_cap.models import Breach, CapContext, Line

__all__ = [
	"Breach",
	"CapContext",
	"Line",
	"breaches_for_asn_doc",
	"breaches_for_asn_rows",
	"breaches_for_purchase_receipt",
	"consumed_from_breach_free_rows",
	"evaluate",
	"format_breaches",
	"get_stock_cap_preview",
	"may_see_stock_figures",
]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_messages
```

Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap asn_module/tests/test_stock_cap_messages.py
git commit -m "feat: add stock cap messages and service API with supplier redaction"
```

---

### Task 6: ASN controller enforcement

**Files:**
- Modify: `asn_module/asn_module/doctype/asn/asn.py:31-37` (the `validate` method), plus a new `before_submit` and two private methods
- Test: `asn_module/asn_module/doctype/asn/test_asn.py` (append a new test class)

**Interfaces:**
- Consumes: `breaches_for_asn_doc`, `format_breaches`, `may_see_stock_figures` from Task 5.
- Produces: `ASN._warn_stock_cap()` and `ASN._validate_stock_cap()`. No new public API.

- [ ] **Step 1: Write the failing test**

Append to `asn_module/asn_module/doctype/asn/test_asn.py`. Note that the existing
`make_test_asn()` helper at line 165 returns an **unsaved** document - it calls
`frappe.get_doc` without inserting - so every test below inserts explicitly.

```python
class TestASNStockCap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		before_tests()

	def _breach(self):
		return SimpleNamespace(
			branch="Mumbai",
			item_code="WIDGET",
			row_idxs=(1,),
			on_hand=90.0,
			in_transit=0.0,
			incoming=20.0,
			projected=110.0,
			cap=100.0,
			allowed_qty=10.0,
		)

	def test_submit_is_blocked_when_cap_is_breached(self):
		asn = make_test_asn(qty=5)
		with patch("asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc", return_value=[]):
			asn.insert()

		with patch(
			"asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc",
			return_value=[self._breach()],
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				asn.submit()

		self.assertIn("WIDGET", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("ASN", asn.name, "docstatus"), 0)

	def test_save_warns_but_succeeds_when_cap_is_breached(self):
		asn = make_test_asn(qty=5)
		frappe.local.message_log = []
		with patch(
			"asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc",
			return_value=[self._breach()],
		):
			asn.insert()

		self.assertTrue(frappe.db.exists("ASN", asn.name))
		messages = " ".join(str(m) for m in frappe.local.message_log or [])
		self.assertIn("WIDGET", messages)

	def test_submit_succeeds_when_no_breach(self):
		asn = make_test_asn(qty=5)
		with patch("asn_module.asn_module.doctype.asn.asn.breaches_for_asn_doc", return_value=[]):
			asn.insert()
			asn.submit()

		self.assertEqual(frappe.db.get_value("ASN", asn.name, "docstatus"), 1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn --test test_submit_is_blocked_when_cap_is_breached
```

Expected: FAIL with `AttributeError: ... does not have the attribute 'breaches_for_asn_doc'`.

- [ ] **Step 3: Add the imports**

In `asn_module/asn_module/doctype/asn/asn.py`, directly after the existing `from asn_module.qr_engine.generate import generate_barcode, generate_qr` line (line 13), add:

```python
from asn_module.stock_cap.api import breaches_for_asn_doc
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures
```

- [ ] **Step 4: Wire validate and before_submit**

Replace the `validate` method at `asn_module/asn_module/doctype/asn/asn.py:31-37` with:

```python
	def validate(self):
		self._validate_items_present()
		self._validate_item_qty()
		self._sync_supplier_invoice_amount_from_items()
		super().validate()
		self._validate_supplier_invoice_unique()
		self._validate_po_qty()
		self._warn_stock_cap()

	def before_submit(self):
		self._validate_stock_cap()
```

Then add both methods immediately after `_validate_po_qty` ends (after line 251):

```python
	def _warn_stock_cap(self):
		"""Surface cap breaches on save without blocking. Drafts must always be saveable."""
		breaches = breaches_for_asn_doc(self)
		if not breaches:
			return

		frappe.msgprint(
			format_breaches(breaches, detailed=may_see_stock_figures()),
			title=_("Stock Cap Warning"),
			indicator="orange",
		)

	def _validate_stock_cap(self):
		"""Block submission. Runs in before_submit so nothing is written before the block."""
		breaches = breaches_for_asn_doc(self)
		if not breaches:
			return

		frappe.throw(
			format_breaches(breaches, detailed=may_see_stock_figures()),
			title=_("Stock Cap Exceeded"),
		)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn
```

Expected: every existing ASN test PASSES plus the 3 new ones.

- [ ] **Step 6: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/asn_module/doctype/asn/asn.py asn_module/asn_module/doctype/asn/test_asn.py
git commit -m "feat: warn on ASN save and block ASN submit when stock cap is breached"
```

---

### Task 7: Purchase Receipt enforcement

**Files:**
- Modify: `asn_module/handlers/purchase_receipt.py`
- Modify: `asn_module/hooks.py:159-163`
- Test: `asn_module/handlers/tests/test_purchase_receipt.py` (append a new test class)

**Interfaces:**
- Consumes: `breaches_for_purchase_receipt`, `format_breaches`, `may_see_stock_figures` from Task 5.
- Produces: `on_purchase_receipt_before_submit(doc, method=None)`, registered as a `doc_events` hook.

- [ ] **Step 1: Write the failing test**

Append to `asn_module/handlers/tests/test_purchase_receipt.py`:

```python
from types import SimpleNamespace
from unittest.mock import patch

from asn_module.handlers.purchase_receipt import on_purchase_receipt_before_submit


class TestPurchaseReceiptStockCap(FrappeTestCase):
	def _breach(self):
		return SimpleNamespace(
			branch="Mumbai",
			item_code="WIDGET",
			row_idxs=(1,),
			on_hand=95.0,
			in_transit=0.0,
			incoming=20.0,
			projected=115.0,
			cap=100.0,
			allowed_qty=5.0,
		)

	def test_submit_is_blocked_when_cap_is_breached(self):
		doc = SimpleNamespace(name="PR-0001", is_return=0, branch="Mumbai", asn=None, items=[])
		with patch(
			"asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt",
			return_value=[self._breach()],
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				on_purchase_receipt_before_submit(doc)
		self.assertIn("WIDGET", str(ctx.exception))

	def test_submit_is_allowed_when_no_breach(self):
		doc = SimpleNamespace(name="PR-0002", is_return=0, branch="Mumbai", asn=None, items=[])
		with patch(
			"asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt", return_value=[]
		):
			self.assertIsNone(on_purchase_receipt_before_submit(doc))

	def test_handler_passes_the_receipt_through_for_asn_exclusion(self):
		doc = SimpleNamespace(name="PR-0003", is_return=0, branch="Mumbai", asn="ASN-0007", items=[])
		with patch(
			"asn_module.handlers.purchase_receipt.breaches_for_purchase_receipt", return_value=[]
		) as spy:
			on_purchase_receipt_before_submit(doc)
		spy.assert_called_once_with(doc)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.handlers.tests.test_purchase_receipt --test test_submit_is_blocked_when_cap_is_breached
```

Expected: FAIL with `ImportError: cannot import name 'on_purchase_receipt_before_submit'`.

- [ ] **Step 3: Write the handler**

Add these imports to `asn_module/handlers/purchase_receipt.py`, directly after the existing `from asn_module.traceability import emit_asn_item_transition` line:

```python
from asn_module.stock_cap.api import breaches_for_purchase_receipt
from asn_module.stock_cap.messages import format_breaches, may_see_stock_figures
```

Then add this function at module level, immediately after `create_from_asn`:

```python
def on_purchase_receipt_before_submit(doc, method=None):
	"""Block a receipt that would carry an item above its branch maximum.

	Runs before_submit so no stock ledger entry is written before the block. The receipt's
	own ASN is excluded from the in-transit figure inside breaches_for_purchase_receipt.
	"""
	breaches = breaches_for_purchase_receipt(doc)
	if not breaches:
		return

	frappe.throw(
		format_breaches(breaches, detailed=may_see_stock_figures()),
		title=_("Stock Cap Exceeded"),
	)
```

- [ ] **Step 4: Register the hook**

In `asn_module/hooks.py`, replace the `Purchase Receipt` entry at lines 160-163 with:

```python
	"Purchase Receipt": {
		"before_submit": "asn_module.handlers.purchase_receipt.on_purchase_receipt_before_submit",
		"on_submit": "asn_module.handlers.purchase_receipt.on_purchase_receipt_submit",
		"on_trash": "asn_module.handlers.purchase_receipt.on_purchase_receipt_trash",
	},
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.handlers.tests.test_purchase_receipt
bench --site frappe16.localhost run-tests --module asn_module.tests.test_hooks
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/handlers/purchase_receipt.py asn_module/hooks.py asn_module/handlers/tests/test_purchase_receipt.py
git commit -m "feat: block purchase receipt submit when stock cap is breached"
```

---

### Task 8: Portal and bulk upload integration

**Files:**
- Modify: `asn_module/templates/pages/asn_new_services.py` — `create_bulk_asns_for_supplier` (validation phase, around line 609) and `insert_and_submit_asn` (lines 621-639)
- Test: `asn_module/templates/pages/test_asn_new_services.py` (append a new test class)

**Interfaces:**
- Consumes: `breaches_for_asn_rows`, `consumed_from_breach_free_rows` from Task 5; `error_entry` and `PortalValidationError` already defined in `asn_new_services.py`.
- Produces: no new public API. The cap becomes part of the existing all-or-nothing validation contract.

- [ ] **Step 1: Write the failing test**

Append to `asn_module/templates/pages/test_asn_new_services.py`. The existing
`_make_bulk_row` helpers are per-class methods, and `create_bulk_asns_for_supplier`
validates against real Purchase Orders, so these tests need module-level fixtures
backed by a genuine PO. Add them alongside the new test class.

```python
from types import SimpleNamespace
from unittest.mock import patch

from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order
from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
	create_bulk_asns_for_supplier,
)


def _bulk_fixture():
	"""A real submitted PO plus the supplier, so bulk validation has something to resolve."""
	po = create_purchase_order()
	return po, po.supplier, po.items[0]


def _bulk_row(po, po_item, *, row_number, invoice_no, qty):
	return ParsedBulkRow(
		row_number=row_number,
		supplier_invoice_no=invoice_no,
		supplier_invoice_date=_test_dates()["supplier_invoice_date"],
		expected_delivery_date=_test_dates()["expected_delivery_date"],
		lr_no="",
		lr_date="",
		transporter_name="",
		vehicle_number="",
		driver_contact="",
		supplier_invoice_amount=qty * float(po_item.rate or 1),
		purchase_order=po.name,
		sr_no=str(po_item.idx),
		item_code=po_item.item_code,
		qty=qty,
		rate=float(po_item.rate or 1),
	)


class TestBulkUploadStockCap(FrappeTestCase):
	def _breach(self):
		return SimpleNamespace(
			branch="Mumbai",
			item_code="WIDGET",
			row_idxs=(1,),
			on_hand=95.0,
			in_transit=0.0,
			incoming=20.0,
			projected=115.0,
			cap=100.0,
			allowed_qty=5.0,
		)

	def setUp(self):
		self.po, self.supplier, self.po_item = _bulk_fixture()

	def _one_group(self):
		return [_bulk_row(self.po, self.po_item, row_number=1, invoice_no="CAP-INV-1", qty=1)]

	def _two_groups_same_item(self):
		return [
			_bulk_row(self.po, self.po_item, row_number=1, invoice_no="CAP-INV-1", qty=1),
			_bulk_row(self.po, self.po_item, row_number=2, invoice_no="CAP-INV-2", qty=1),
		]

	def test_breach_prevents_any_asn_from_being_created(self):
		inserted = []

		def fake_insert(**kwargs):
			inserted.append(kwargs)
			return SimpleNamespace(name="ASN-TEST")

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
			return_value=[self._breach()],
		):
			with self.assertRaises(PortalValidationError) as ctx:
				create_bulk_asns_for_supplier(
					supplier=self.supplier, rows=self._one_group(), insert_asn=fake_insert
				)

		self.assertEqual(inserted, [])
		messages = " ".join(error.get("message", "") for error in ctx.exception.errors)
		self.assertIn("WIDGET", messages)
		self.assertIn("No ASNs created", messages)

	def test_no_breach_allows_all_asns_to_be_created(self):
		inserted = []

		def fake_insert(**kwargs):
			inserted.append(kwargs)
			return SimpleNamespace(name=f"ASN-{len(inserted)}")

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows", return_value=[]
		):
			names = create_bulk_asns_for_supplier(
				supplier=self.supplier, rows=self._one_group(), insert_asn=fake_insert
			)

		self.assertEqual(len(names), len(inserted))
		self.assertTrue(names)

	def test_consumed_headroom_is_carried_across_groups(self):
		seen_consumed = []

		def fake_breaches(payload_rows, exclude_asn_name=None, consumed=None):
			seen_consumed.append(dict(consumed or {}))
			return []

		with patch(
			"asn_module.templates.pages.asn_new_services.breaches_for_asn_rows",
			side_effect=fake_breaches,
		):
			with patch(
				"asn_module.templates.pages.asn_new_services.consumed_from_breach_free_rows",
				return_value={("Mumbai", self.po_item.item_code): 1.0},
			):
				create_bulk_asns_for_supplier(
					supplier=self.supplier,
					rows=self._two_groups_same_item(),
					insert_asn=lambda **kwargs: SimpleNamespace(name="ASN-X"),
				)

		self.assertGreaterEqual(len(seen_consumed), 2)
		self.assertEqual(seen_consumed[0], {})
		self.assertEqual(seen_consumed[1], {("Mumbai", self.po_item.item_code): 1.0})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site frappe16.localhost run-tests --module asn_module.templates.pages.test_asn_new_services --test test_breach_prevents_any_asn_from_being_created
```

Expected: FAIL with `AttributeError: ... does not have the attribute 'breaches_for_asn_rows'`.

- [ ] **Step 3: Add the import**

Alongside the other `asn_module` imports at the top of `asn_module/templates/pages/asn_new_services.py`, add:

```python
from asn_module.stock_cap.api import breaches_for_asn_rows, consumed_from_breach_free_rows
```

- [ ] **Step 4: Add the cap check to the validation phase**

In `create_bulk_asns_for_supplier`, insert this single line immediately before the existing `if errors:` block (currently line 609):

```python
	_collect_stock_cap_errors(asn_payloads, errors)
```

Then add this function at module level, directly after `create_bulk_asns_for_supplier`:

```python
def _collect_stock_cap_errors(asn_payloads: list[tuple[dict, list[dict]]], errors: list[dict]):
	"""Evaluate the cap across every parsed payload before any ASN is inserted.

	Runs in the validation phase so the function keeps its all-or-nothing contract: the
	insert loop that follows has no error handling, and partially-submitted ASNs cannot
	be rolled back cleanly. Headroom consumed by an earlier group is carried forward so
	one upload cannot drive an item past its maximum across several ASNs, mirroring how
	running_remaining already guards the PO quantity check.
	"""
	consumed: dict[tuple[str, str], float] = {}

	for header, items in asn_payloads:
		rows = [
			{
				"idx": index,
				"purchase_order": item.get("purchase_order"),
				"purchase_order_item": item.get("purchase_order_item"),
				"item_code": item.get("item_code"),
				"qty": flt(item.get("qty")),
			}
			for index, item in enumerate(items, start=1)
		]

		for breach in breaches_for_asn_rows(rows, consumed=consumed):
			errors.append(
				error_entry(
					field="items_csv",
					invoice_no=header.get("supplier_invoice_no"),
					message=_(
						"Item {0}: this upload would take branch {1} to {2}, above its maximum of {3}."
					).format(breach.item_code, breach.branch, breach.projected, breach.cap),
				)
			)

		for key, qty in consumed_from_breach_free_rows(rows).items():
			consumed[key] = consumed.get(key, 0.0) + qty
```

- [ ] **Step 5: Surface the portal submit failure as a field error**

Replace `insert_and_submit_asn` at `asn_module/templates/pages/asn_new_services.py:621-639` with:

```python
def insert_and_submit_asn(*, supplier: str, header: dict, items: list[dict]):
	doc_payload = {
		"doctype": "ASN",
		"supplier": supplier,
		"supplier_invoice_no": header.get("supplier_invoice_no"),
		"supplier_invoice_date": header.get("supplier_invoice_date"),
		"expected_delivery_date": header.get("expected_delivery_date"),
		"lr_no": header.get("lr_no"),
		"lr_date": header.get("lr_date"),
		"transporter_name": header.get("transporter_name"),
		"vehicle_number": header.get("vehicle_number"),
		"driver_contact": header.get("driver_contact"),
		"items": items,
	}
	doc_payload["supplier_invoice_amount"] = header["supplier_invoice_amount"]
	asn = frappe.get_doc(doc_payload)
	asn.flags.ignore_permissions = True
	asn.insert()
	try:
		asn.submit()
	except frappe.ValidationError as exc:
		# Render the block as a field-level portal error rather than a raw traceback.
		raise PortalValidationError([error_entry(field="items_csv", message=str(exc))]) from exc
	return asn
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
bench --site frappe16.localhost run-tests --module asn_module.templates.pages.test_asn_new_services
```

Expected: every existing test PASSES plus the 3 new ones.

- [ ] **Step 7: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/templates/pages/asn_new_services.py asn_module/templates/pages/test_asn_new_services.py
git commit -m "feat: enforce stock cap in bulk upload validation phase"
```

---

### Task 9: Property tests

**Files:**
- Create: `asn_module/property_tests/test_stock_cap_properties.py`

**Interfaces:**
- Consumes: `Line`, `CapContext`, `evaluate` from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the property tests**

Create `asn_module/property_tests/test_stock_cap_properties.py`:

```python
from frappe.tests import UnitTestCase
from hypothesis import given
from hypothesis import strategies as st

from asn_module.property_tests import settings  # noqa: F401  (loads HYPOTHESIS_PROFILE)
from asn_module.stock_cap.evaluate import evaluate
from asn_module.stock_cap.models import CapContext, Line

BRANCH = "B"
ITEM = "I"
WH = "W"

quantities = st.floats(min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False)
caps = st.floats(min_value=0.01, max_value=10_000, allow_nan=False, allow_infinity=False)


def _context(cap: float, on_hand: float, in_transit: float) -> CapContext:
	return CapContext(
		cap_warehouses={BRANCH: frozenset({WH})},
		max_stock={ITEM: cap},
		on_hand={(BRANCH, ITEM): on_hand},
		in_transit={(BRANCH, ITEM): in_transit},
	)


def _line(qty: float) -> Line:
	return Line(branch=BRANCH, item_code=ITEM, warehouse=WH, stock_qty=qty, row_idx=1)


class TestStockCapProperties(UnitTestCase):
	@given(caps, quantities, quantities, quantities, quantities)
	def test_projected_is_monotonic_in_declared_quantity(self, cap, on_hand, in_transit, qty, extra):
		context = _context(cap, on_hand, in_transit)
		low = evaluate([_line(qty)], context)
		high = evaluate([_line(qty + extra)], context)
		if low:
			self.assertTrue(high, "a larger quantity must not turn a breach into a pass")
			self.assertLessEqual(low[0].projected, high[0].projected)

	@given(caps, quantities, quantities, quantities)
	def test_breach_holds_exactly_when_projected_exceeds_cap(self, cap, on_hand, in_transit, qty):
		breaches = evaluate([_line(qty)], _context(cap, on_hand, in_transit))
		self.assertEqual(bool(breaches), (on_hand + in_transit + qty) > cap)

	@given(caps, quantities, quantities, quantities)
	def test_allowed_qty_is_the_largest_non_breaching_quantity(self, cap, on_hand, in_transit, qty):
		context = _context(cap, on_hand, in_transit)
		breaches = evaluate([_line(qty)], context)
		if not breaches:
			return

		self.assertEqual(evaluate([_line(breaches[0].allowed_qty)], context), [])
```

- [ ] **Step 2: Run the property tests**

```bash
HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests \
  --module asn_module.property_tests.test_stock_cap_properties --lightmode
```

Expected: 3 tests PASS.

- [ ] **Step 3: Run deeper locally**

```bash
HYPOTHESIS_PROFILE=local bench --site frappe16.localhost run-tests \
  --module asn_module.property_tests.test_stock_cap_properties --lightmode
```

Expected: 3 tests PASS. If Hypothesis reports a counterexample, keep the minimised case, add it as a deterministic test in `asn_module/tests/test_stock_cap_evaluate.py`, and fix the evaluator. Do not widen the strategy bounds to hide a real failure.

- [ ] **Step 4: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/property_tests/test_stock_cap_properties.py
git commit -m "test: add stock cap property tests"
```

---

### Task 10: Cypress end-to-end coverage

**Files:**
- Modify: `asn_module/utils/cypress_helpers.py`
- Create: `cypress/integration/nightly/stock_cap_e2e.js`

**Interfaces:**
- Consumes: the whole feature.
- Produces: whitelisted `asn_module.utils.cypress_helpers.seed_stock_cap_context`.

- [ ] **Step 1: Write the seeding helper**

Append to `asn_module/utils/cypress_helpers.py`:

```python
@frappe.whitelist()
def seed_stock_cap_context():
	"""Seed a branch with one cap warehouse and an item capped below the PO quantity.

	Returns everything the stock cap spec needs to drive the desk form.
	"""
	branch = "_Cypress Cap Branch"
	if not frappe.db.exists("Branch", branch):
		frappe.get_doc({"doctype": "Branch", "branch": branch}).insert(ignore_permissions=True)

	context = seed_supplier_context()
	purchase_order = context["purchase_orders"][0]
	frappe.db.set_value("Purchase Order", purchase_order, "branch", branch)

	po_item = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=["name", "item_code", "warehouse", "qty"],
		limit=1,
	)[0]

	frappe.db.delete("ASN Stock Cap Warehouse", {"warehouse": po_item.warehouse})
	if frappe.db.exists("ASN Stock Cap Settings", branch):
		frappe.delete_doc("ASN Stock Cap Settings", branch, force=True)

	frappe.get_doc(
		{
			"doctype": "ASN Stock Cap Settings",
			"branch": branch,
			"enabled": 1,
			"warehouses": [{"warehouse": po_item.warehouse}],
		}
	).insert(ignore_permissions=True)

	# Cap at half the PO quantity, so a full-quantity ASN always breaches and a quarter never does.
	frappe.db.set_value("Item", po_item.item_code, "custom_max_stock", flt(po_item.qty) / 2)
	frappe.db.commit()

	return {
		"branch": branch,
		"supplier": context["supplier"],
		"purchase_order": purchase_order,
		"item_code": po_item.item_code,
		"warehouse": po_item.warehouse,
		"breaching_qty": flt(po_item.qty),
		"passing_qty": flt(po_item.qty) / 4,
	}
```

If `seed_supplier_context` does not already return a `supplier` key, add it there rather than re-deriving the supplier here.

- [ ] **Step 2: Write the Cypress spec**

Create `cypress/integration/nightly/stock_cap_e2e.js`:

```javascript
const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN stock cap", () => {
	let seeded;

	before(() => {
		cy.login();
		cy.seed_context("asn_module.utils.cypress_helpers.seed_stock_cap_context").then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login();
	});

	const newAsnWithQty = (qty) => {
		cy.visit(route("asn/new"), { failOnStatusCode: false });
		cy.get(".form-layout", { timeout: 20000 }).should("exist");
		cy.fill_field("supplier", seeded.supplier, "Link");
		cy.get('[data-fieldname="items"] .grid-add-row').click();
		cy.get('[data-fieldname="purchase_order"]:visible')
			.first()
			.type(`${seeded.purchase_order}{enter}`, { delay: 30 });
		cy.get('[data-fieldname="qty"]:visible').first().clear().type(String(qty));
	};

	it("submits when projected stock stays within the cap", () => {
		newAsnWithQty(seeded.passing_qty);
		cy.get(".primary-action").contains("Save").click();
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		cy.get(".primary-action").contains("Submit").click();
		cy.get(".modal-footer .btn-primary:visible").click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("not.contain", "Draft");
	});

	it("warns on save but still saves when the cap is breached", () => {
		newAsnWithQty(seeded.breaching_qty);
		cy.get(".primary-action").contains("Save").click();
		cy.get(".modal", { timeout: 20000 }).should("contain", seeded.item_code);
		cy.get(".modal-header .btn-modal-close:visible").first().click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("contain", "Draft");
	});

	it("blocks submit and leaves the ASN in draft when the cap is breached", () => {
		cy.get(".primary-action").contains("Submit").click();
		cy.get(".modal-footer .btn-primary:visible").click();
		cy.get(".modal", { timeout: 20000 }).should("contain", "exceeds maximum");
		cy.get(".modal-header .btn-modal-close:visible").first().click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("contain", "Draft");
	});
});
```

- [ ] **Step 3: Run the spec**

```bash
bench run-ui-tests asn_module --headless --spec cypress/integration/nightly/stock_cap_e2e.js
```

Expected: 3 tests PASS. If selectors drift from the current desk theme, adjust them against a real run rather than weakening the assertions - each test must still prove the document's state, not merely that a dialog appeared.

- [ ] **Step 4: Commit**

```bash
npx eslint cypress/ asn_module/
ruff format asn_module/ && ruff check asn_module/
git add cypress/integration/nightly/stock_cap_e2e.js asn_module/utils/cypress_helpers.py
git commit -m "test: add stock cap end-to-end coverage"
```

---

### Task 11: Full suite and coverage gate

**Files:** none, unless coverage falls short.

**Interfaces:**
- Consumes: every prior task.
- Produces: nothing.

- [ ] **Step 1: Run the full suite on v16 with coverage**

```bash
bench --site frappe16.localhost run-tests --app asn_module --with-coverage
```

Expected: all tests PASS, coverage at or above 96%.

- [ ] **Step 2: Run the full suite on v15**

```bash
bench --site development.localhost run-tests --app asn_module
```

Expected: all tests PASS.

- [ ] **Step 3: Run every property module**

```bash
for m in \
  asn_module.property_tests.test_asn_new_services_properties \
  asn_module.property_tests.test_scan_code_properties \
  asn_module.property_tests.test_token_properties \
  asn_module.property_tests.test_stock_cap_properties; do
  HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests --module "$m" --lightmode
done
```

Expected: all PASS.

- [ ] **Step 4: Run pre-commit**

```bash
pre-commit run --all-files
```

Expected: all hooks pass.

- [ ] **Step 5: Close any coverage gap**

If coverage is below 96%, find the uncovered lines and add real tests for them. Do not lower the threshold and do not add tests that assert nothing.

```bash
python3 -m coverage report --show-missing | grep stock_cap
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: close stock cap coverage gaps"
```

---

## Deployment Note

The cap stays inert on production until `Item.custom_max_stock` is created there. It did not exist on `trikayacoatings.frappe.cloud` as of 2026-07-28. Definition to create:

- DocType: `Item`
- Fieldname: `custom_max_stock`
- Fieldtype: `Float`
- Label: `Max Stock`
- Insert after: `safety_stock`
- Non-negative: yes

`Purchase Order.branch` and `Purchase Receipt.branch` already exist on production via the `Branch` Accounting Dimension and need no action.
