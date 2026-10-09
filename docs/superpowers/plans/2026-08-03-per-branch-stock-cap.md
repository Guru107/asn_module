# Per-Branch Stock Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the stock cap ceiling vary per branch, replacing the single global `Item.custom_max_stock` with per-(item, branch) records.

**Architecture:** A new `ASN Item Branch Cap` doctype holds `(item, branch, max_qty)`, named `{branch}::{item}` so the primary key enforces uniqueness. `CapContext.max_stock` re-keys from `item_code` to `(branch, item_code)`; `evaluate()` changes only its two cap lookups and stays pure. Stock is still pooled across a branch's cap warehouses — only the ceiling varies. `Item.custom_max_stock` and everything that created it are removed.

**Tech Stack:** Frappe v15/v16, ERPNext, Python 3.10+, `FrappeTestCase`, Hypothesis, Cypress.

**Spec:** [2026-08-03-per-branch-stock-cap-design.md](../specs/2026-08-03-per-branch-stock-cap-design.md)

## Global Constraints

- Python style: **tab indentation**, double quotes, 110 char line length (`ruff`, config in `pyproject.toml`).
- Must run on both Frappe/ERPNext v15 (`development.localhost`, bench at `/root/workspace/bench15`) and v16 (`frappe16.localhost`, bench at `/root/workspace/bench16`).
- All user-visible strings wrapped in `_()`.
- Test naming: `test_<what>_<expected_outcome>`.
- Fail open on absent configuration: a missing table, missing settings, or a zero/absent cap silently skips the check. Never raise because configuration is absent. This does **not** license failing open on a permission check.
- Comparison is **strictly greater**: `projected == cap` is allowed.
- Quantities compared against `Bin.actual_qty` are always in **stock UOM**.
- The cap is **advisory, not transactional**. No locking. Do not add `FOR UPDATE`.
- Never disclose On Hand, In Transit, or Maximum Stock to users without `read` permission on `Item`.
- Run bench commands from the bench directory. Add `--lightmode` on v16 to avoid a pre-existing india_compliance bootstrap failure unrelated to this work.

## File Structure

**Create:**

| File | Responsibility |
| --- | --- |
| `asn_module/asn_module/doctype/asn_item_branch_cap/__init__.py` | package marker |
| `asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.json` | doctype definition |
| `asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.py` | controller: validation + configuration warning |
| `asn_module/tests/test_asn_item_branch_cap.py` | doctype tests |
| `asn_module/patches/remove_item_max_stock_field.py` | delete the retired custom field |

**Modify:**

| File | Change |
| --- | --- |
| `asn_module/stock_cap/models.py` | `CapContext.max_stock` re-keyed to `(branch, item_code)` |
| `asn_module/stock_cap/evaluate.py` | two cap lookups take `(branch, item_code)` |
| `asn_module/stock_cap/fetch.py` | `_fetch_max_stock(branches, item_codes)` reads the new doctype |
| `asn_module/setup.py` | drop `setup_item_fields` |
| `asn_module/patches.txt` | swap create-patch for remove-patch |
| `asn_module/tests/test_hooks.py` | drop the two retired-field tests |
| `asn_module/tests/test_stock_cap_evaluate.py` | re-key `_context`, add two-branch case |
| `asn_module/tests/test_stock_cap_fetch.py` | cap rows instead of the item field |
| `asn_module/tests/test_stock_cap_api.py` | cap rows instead of the item field |
| `asn_module/templates/pages/test_asn_new_services.py` | cap row instead of the item field |
| `asn_module/property_tests/test_stock_cap_properties.py` | re-key `_context` |
| `asn_module/utils/cypress_helpers.py` | seeder creates a cap row |

**Delete:**

| File | Reason |
| --- | --- |
| `asn_module/custom_fields/item.py` | field retired |
| `asn_module/patches/create_item_max_stock_field.py` | superseded by the removal patch |

---

### Task 1: The ASN Item Branch Cap doctype

**Files:**
- Create: `asn_module/asn_module/doctype/asn_item_branch_cap/__init__.py`
- Create: `asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.json`
- Create: `asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.py`
- Test: `asn_module/tests/test_asn_item_branch_cap.py`

**Interfaces:**
- Consumes: nothing.
- Produces: DocType `ASN Item Branch Cap` with fields `item`, `branch`, `max_qty`, named `{branch}::{item}`. Task 3 queries it.

- [ ] **Step 1: Write the failing test**

Create `asn_module/tests/test_asn_item_branch_cap.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.utils.test_setup import before_tests

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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_asn_item_branch_cap --lightmode
```

Expected: FAIL with `DocType ASN Item Branch Cap not found`.

- [ ] **Step 3: Create the doctype JSON**

`asn_module/asn_module/doctype/asn_item_branch_cap/__init__.py` — empty file.

`asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.json`:

```json
{
 "actions": [],
 "autoname": "format:{branch}::{item}",
 "creation": "2026-08-03 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["item", "branch", "max_qty"],
 "fields": [
  {
   "fieldname": "item",
   "fieldtype": "Link",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Item",
   "options": "Item",
   "reqd": 1
  },
  {
   "fieldname": "branch",
   "fieldtype": "Link",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Branch",
   "options": "Branch",
   "reqd": 1
  },
  {
   "description": "Largest quantity of this item allowed in this branch, in stock UOM. 0 means no cap.",
   "fieldname": "max_qty",
   "fieldtype": "Float",
   "in_list_view": 1,
   "label": "Max Qty",
   "non_negative": 1
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-08-03 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "ASN Module",
 "name": "ASN Item Branch Cap",
 "naming_rule": "Expression",
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

- [ ] **Step 4: Write the controller**

`asn_module/asn_module/doctype/asn_item_branch_cap/asn_item_branch_cap.py`:

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

NAME_SEPARATOR = "::"


class ASNItemBranchCap(Document):
	def validate(self):
		self._validate_non_negative_max_qty()
		self._validate_no_separator_in_keys()
		self._warn_if_branch_has_no_cap_warehouses()

	def _validate_non_negative_max_qty(self):
		if flt(self.max_qty) < 0:
			frappe.throw(_("Max Qty cannot be negative."))

	def _validate_no_separator_in_keys(self):
		"""The document name is {branch}::{item}, so the key enforces uniqueness.

		A branch or item containing the separator could collide two distinct pairs onto
		one record, which would silently overwrite a cap.
		"""
		for fieldname, label in (("branch", _("Branch")), ("item", _("Item"))):
			if NAME_SEPARATOR in (self.get(fieldname) or ""):
				frappe.throw(
					_("{0} must not contain {1}.").format(label, NAME_SEPARATOR)
				)

	def _warn_if_branch_has_no_cap_warehouses(self):
		"""Surface a cap that cannot take effect yet, at the moment someone sets it.

		The rule needs two things: this ceiling, and an enabled ASN Stock Cap Settings
		naming the warehouses whose stock counts. Without the second, this row is inert
		and nothing would otherwise say so. Deliberately a warning, not a block: the
		fail-open rule stands, and ceilings may legitimately be set before warehouses.
		"""
		if not self.branch:
			return

		settings = frappe.db.get_value(
			"ASN Stock Cap Settings", self.branch, ["name", "enabled"], as_dict=True
		)
		if settings and settings.enabled:
			has_warehouse = frappe.db.exists(
				"ASN Stock Cap Warehouse", {"parent": settings.name, "parenttype": "ASN Stock Cap Settings"}
			)
			if has_warehouse:
				return

		frappe.msgprint(
			_(
				"Branch {0} has no enabled ASN Stock Cap Settings, so this limit will not be "
				"enforced until its cap warehouses are configured."
			).format(self.branch),
			title=_("Cap Not Yet Enforced"),
			indicator="orange",
		)
```

- [ ] **Step 5: Sync the doctype to both benches**

```bash
cd /root/workspace/bench16 && bench --site frappe16.localhost reload-doctype "ASN Item Branch Cap"
cd /root/workspace/bench15 && bench --site development.localhost reload-doctype "ASN Item Branch Cap"
```

If `reload-doctype` reports the doctype is not found, run `bench --site <site> migrate` instead — a brand-new doctype may need a full sync.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_asn_item_branch_cap --lightmode
```

Expected: 7 tests PASS.

- [ ] **Step 7: Verify on v15**

```bash
cd /root/workspace/bench15
bench --site development.localhost run-tests --module asn_module.tests.test_asn_item_branch_cap
```

Expected: 7 tests PASS.

- [ ] **Step 8: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/asn_module/doctype/asn_item_branch_cap asn_module/tests/test_asn_item_branch_cap.py
git commit -m "feat: add ASN Item Branch Cap doctype for per-branch ceilings"
```

---

### Task 2: Re-key the evaluator to (branch, item)

**Files:**
- Modify: `asn_module/stock_cap/models.py` (the `CapContext.max_stock` annotation)
- Modify: `asn_module/stock_cap/evaluate.py:40` and `:48`
- Test: `asn_module/tests/test_stock_cap_evaluate.py`
- Test: `asn_module/property_tests/test_stock_cap_properties.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `CapContext.max_stock: dict[tuple[str, str], float]` keyed `(branch, item_code)`. Task 3 builds this shape.

This task changes only the pure layer. `evaluate.py` and `models.py` must keep importing no `frappe`.

- [ ] **Step 1: Write the failing test**

In `asn_module/tests/test_stock_cap_evaluate.py`, replace the `_context` helper:

```python
def _context(**overrides) -> CapContext:
	defaults = {
		"cap_warehouses": {BRANCH: frozenset({WH})},
		"max_stock": {(BRANCH, ITEM): 100.0},
		"on_hand": {},
		"in_transit": {},
	}
	defaults.update(overrides)
	return CapContext(**defaults)
```

Then update every test in that file that passes `max_stock=` to use the tuple key. There are three:

```python
	def test_no_cap_configured_produces_no_breach(self):
		breaches, accepted = evaluate([_line(500)], _context(max_stock={}))
		self.assertEqual(breaches, [])
		self.assertEqual(accepted, {})

	def test_zero_cap_is_treated_as_uncapped(self):
		breaches, accepted = evaluate([_line(500)], _context(max_stock={(BRANCH, ITEM): 0.0}))
		self.assertEqual(breaches, [])
		self.assertEqual(accepted, {})
```

and the deterministic-sort test, whose context is built inline:

```python
	def test_breaches_are_sorted_deterministically(self):
		context = CapContext(
			cap_warehouses={BRANCH: frozenset({WH})},
			max_stock={(BRANCH, "B_ITEM"): 1.0, (BRANCH, "A_ITEM"): 1.0},
			on_hand={},
			in_transit={},
		)
		lines = [
			Line(branch=BRANCH, item_code="B_ITEM", warehouse=WH, stock_qty=5, row_idx=1),
			Line(branch=BRANCH, item_code="A_ITEM", warehouse=WH, stock_qty=5, row_idx=2),
		]
		breaches, _accepted = evaluate(lines, context)
		self.assertEqual([b.item_code for b in breaches], ["A_ITEM", "B_ITEM"])
```

Add the new behaviour this task exists for, at the end of the class:

```python
	def test_each_branch_uses_its_own_ceiling_for_the_same_item(self):
		other_branch = "Delhi"
		other_wh = "Delhi Store - MC"
		context = CapContext(
			cap_warehouses={BRANCH: frozenset({WH}), other_branch: frozenset({other_wh})},
			max_stock={(BRANCH, ITEM): 100.0, (other_branch, ITEM): 10.0},
			on_hand={},
			in_transit={},
		)
		lines = [
			Line(branch=BRANCH, item_code=ITEM, warehouse=WH, stock_qty=50, row_idx=1),
			Line(branch=other_branch, item_code=ITEM, warehouse=other_wh, stock_qty=50, row_idx=2),
		]

		breaches, _accepted = evaluate(lines, context)

		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0].branch, other_branch)
		self.assertEqual(breaches[0].cap, 10.0)

	def test_cap_for_another_branch_does_not_apply(self):
		context = _context(max_stock={("Some Other Branch", ITEM): 1.0})

		breaches, accepted = evaluate([_line(500)], context)

		self.assertEqual(breaches, [])
		self.assertEqual(accepted, {})
```

In `asn_module/property_tests/test_stock_cap_properties.py`, replace `_context`:

```python
def _context(cap: float, on_hand: float, in_transit: float) -> CapContext:
	return CapContext(
		cap_warehouses={BRANCH: frozenset({WH})},
		max_stock={(BRANCH, ITEM): cap},
		on_hand={(BRANCH, ITEM): on_hand},
		in_transit={(BRANCH, ITEM): in_transit},
	)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_evaluate --lightmode
```

Expected: FAIL. The cap lookup still uses `item_code`, so a `(branch, item)` key never matches and every capped case now reports no breach.

- [ ] **Step 3: Re-key the dataclass**

In `asn_module/stock_cap/models.py`, in `CapContext`, replace the `max_stock` line:

```python
	max_stock: dict[tuple[str, str], float]
```

and update the class docstring to name the key:

```python
@dataclass(frozen=True)
class CapContext:
	"""Everything the evaluator needs, as plain data. Built by fetch_cap_context.

	``max_stock`` is keyed by (branch, item_code): the same item may carry a different
	ceiling in each branch. ``on_hand`` and ``in_transit`` share that key because stock is
	pooled across the branch's cap warehouses.
	"""
```

- [ ] **Step 4: Re-key the two lookups**

In `asn_module/stock_cap/evaluate.py`, line 40 becomes:

```python
		if _as_float(context.max_stock.get((line.branch, line.item_code))) <= 0:
```

and line 48 becomes:

```python
		cap = _as_float(context.max_stock.get((branch, item_code)))
```

Nothing else in the file changes.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_evaluate --lightmode
HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests --module asn_module.property_tests.test_stock_cap_properties --lightmode
```

Expected: evaluate tests PASS (2 more than before), 3 property tests PASS.

- [ ] **Step 6: Confirm the pure layer is still pure**

```bash
grep -n "frappe" asn_module/stock_cap/evaluate.py asn_module/stock_cap/models.py
```

Expected: no import of `frappe` in either file. A docstring mention is fine.

- [ ] **Step 7: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap/models.py asn_module/stock_cap/evaluate.py asn_module/tests/test_stock_cap_evaluate.py asn_module/property_tests/test_stock_cap_properties.py
git commit -m "feat: key the stock cap ceiling by branch and item"
```

---

### Task 3: Read ceilings from the new doctype

**Files:**
- Modify: `asn_module/stock_cap/fetch.py` — `fetch_cap_context` call site and `_fetch_max_stock`
- Modify: `asn_module/utils/cypress_helpers.py:403`
- Test: `asn_module/tests/test_stock_cap_fetch.py`
- Test: `asn_module/tests/test_stock_cap_api.py:147` and `:291`
- Test: `asn_module/templates/pages/test_asn_new_services.py:570`

**Interfaces:**
- Consumes: DocType `ASN Item Branch Cap` (Task 1); `CapContext.max_stock` keyed `(branch, item_code)` (Task 2).
- Produces: `_fetch_max_stock(branches: list[str], item_codes: list[str]) -> dict[tuple[str, str], float]`.

- [ ] **Step 1: Write the failing test**

In `asn_module/tests/test_stock_cap_fetch.py`, the `TestStockCapFetch.setUp` currently sets the retired item field. Replace that line:

```python
		frappe.db.set_value("Item", ITEM, "custom_max_stock", 100)
```

with a cap row, and clear the table alongside the other fixtures:

```python
		frappe.db.delete("ASN Item Branch Cap")
		frappe.db.delete("ASN Stock Cap Warehouse")
		frappe.db.delete("ASN Stock Cap Settings")
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": ITEM, "max_qty": 100}
		).insert(ignore_permissions=True)
```

Replace `test_max_stock_is_read_from_item` with:

```python
	def test_max_stock_is_read_from_the_branch_cap_row(self):
		self._make_settings()
		self.assertEqual(fetch_cap_context([self._line()]).max_stock[(BRANCH, ITEM)], 100.0)

	def test_cap_row_for_another_branch_is_not_returned(self):
		self._make_settings()
		other = "_Test Fetch Branch Other"
		if not frappe.db.exists("Branch", other):
			frappe.get_doc({"doctype": "Branch", "branch": other}).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": other, "item": ITEM, "max_qty": 7}
		).insert(ignore_permissions=True)

		max_stock = fetch_cap_context([self._line()]).max_stock

		self.assertEqual(max_stock, {(BRANCH, ITEM): 100.0})
```

Replace `test_missing_max_stock_column_yields_empty_caps` — the guard is now a table check, not a column check:

```python
	def test_missing_cap_table_yields_empty_caps(self):
		self._make_settings()
		original = frappe.db.table_exists

		def fake_table_exists(doctype, *args, **kwargs):
			if doctype == "ASN Item Branch Cap":
				return False
			return original(doctype, *args, **kwargs)

		frappe.db.table_exists = fake_table_exists
		try:
			self.assertEqual(fetch_cap_context([self._line()]).max_stock, {})
		finally:
			frappe.db.table_exists = original
```

In `TestStockCapFetchInTransit.setUp`, replace the line that pins the shared fixture item to zero:

```python
		frappe.db.set_value("Item", self.po_item.item_code, "custom_max_stock", 0, update_modified=False)
```

with the equivalent for the new model — that class asserts in-transit figures only, so it must not be capped:

```python
		# This class only asserts in-transit figures, never cap enforcement. Removing any cap
		# row for the PO item keeps a stray fixture from making self.asn.submit() below raise
		# Stock Cap Exceeded.
		frappe.db.delete("ASN Item Branch Cap", {"item": self.po_item.item_code})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_stock_cap_fetch --lightmode
```

Expected: FAIL. `_fetch_max_stock` still reads `Item.custom_max_stock` and returns a dict keyed by item code, so `max_stock[(BRANCH, ITEM)]` raises `KeyError`.

- [ ] **Step 3: Rewrite the fetcher**

In `asn_module/stock_cap/fetch.py`, replace `_fetch_max_stock` entirely:

```python
def _fetch_max_stock(branches: list[str], item_codes: list[str]) -> dict[tuple[str, str], float]:
	"""Per-branch ceilings, keyed (branch, item_code).

	Guarded on the table rather than a column: a site that has not yet migrated has no
	ASN Item Branch Cap table at all, and the fail-open rule says an unconfigured site
	simply never enforces a cap.
	"""
	if not frappe.db.table_exists("ASN Item Branch Cap"):
		return {}

	rows = frappe.get_all(
		"ASN Item Branch Cap",
		filters={"branch": ["in", branches], "item": ["in", item_codes]},
		fields=["branch", "item", "max_qty"],
		limit_page_length=0,
	)
	return {(row.branch, row.item): flt(row.max_qty) for row in rows}
```

- [ ] **Step 4: Update the call site**

In `fetch_cap_context`, line 48 becomes:

```python
		max_stock=_fetch_max_stock(branches, item_codes),
```

`branches` is already computed on line 34.

These three call sites still write the retired field. They must move in this same task, not a later one: the moment `_fetch_max_stock` reads the new doctype, a fixture setting `Item.custom_max_stock` has no effect, and the suites that assert a breach (`test_stock_cap_api` asserts `len(preview) == 1` and `entry["breached"]`) fail. Reader and fixtures switch together so every task ends green.

- [ ] **Step 5: Move the API test fixtures onto cap rows**

In `asn_module/tests/test_stock_cap_api.py`, find the branch each fixture uses (the test file defines `BRANCH` and `PR_BRANCH` constants) and replace line 147:

```python
		frappe.db.set_value("Item", ITEM, "custom_max_stock", MAX_STOCK)
```

with:

```python
		frappe.db.delete("ASN Item Branch Cap", {"item": ITEM})
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": BRANCH, "item": ITEM, "max_qty": MAX_STOCK}
		).insert(ignore_permissions=True)
```

and line 291:

```python
		frappe.db.set_value("Item", PR_ITEM, "custom_max_stock", PR_MAX_STOCK)
```

with:

```python
		frappe.db.delete("ASN Item Branch Cap", {"item": PR_ITEM})
		frappe.get_doc(
			{"doctype": "ASN Item Branch Cap", "branch": PR_BRANCH, "item": PR_ITEM, "max_qty": PR_MAX_STOCK}
		).insert(ignore_permissions=True)
```

Both constants exist already: `BRANCH`/`ITEM`/`MAX_STOCK` at the top of the file, and `PR_BRANCH`/`PR_ITEM`/`PR_MAX_STOCK` above the Purchase Receipt class. Each `setUp` sets the same branch on its Purchase Order a few lines below, so the cap must be keyed to that branch or it will not apply.

- [ ] **Step 6: Move the bulk upload fixture onto a cap row**

In `asn_module/templates/pages/test_asn_new_services.py`, replace line 570:

```python
		frappe.db.set_value("Item", self.item_code, "custom_max_stock", 100)
```

with a cap row for `self.branch`, which that `setUp` already defines and ensures exists a few lines above:

```python
		frappe.db.delete("ASN Item Branch Cap", {"item": self.item_code})
		frappe.get_doc(
			{
				"doctype": "ASN Item Branch Cap",
				"branch": self.branch,
				"item": self.item_code,
				"max_qty": 100,
			}
		).insert(ignore_permissions=True)
```

- [ ] **Step 7: Move the Cypress seeder onto a cap row**

In `asn_module/utils/cypress_helpers.py`, replace line 403:

```python
	frappe.db.set_value("Item", po_item.item_code, "custom_max_stock", flt(po_item.qty) / 2)
```

with:

```python
	# Cap at half the PO quantity, so a full-quantity ASN always breaches and a quarter never does.
	frappe.db.delete("ASN Item Branch Cap", {"item": po_item.item_code})
	frappe.get_doc(
		{
			"doctype": "ASN Item Branch Cap",
			"branch": branch,
			"item": po_item.item_code,
			"max_qty": flt(po_item.qty) / 2,
		}
	).insert(ignore_permissions=True)
```

`branch` is the `_Cypress Cap Branch` local already defined earlier in that function.

- [ ] **Step 8: Run every affected suite**

```bash
cd /root/workspace/bench16
for m in asn_module.tests.test_stock_cap_fetch \
         asn_module.tests.test_stock_cap_api \
         asn_module.templates.pages.test_asn_new_services; do
  bench --site frappe16.localhost run-tests --module "$m" --lightmode
done
```

Expected: all PASS. These are the suites whose fixtures just moved; a failure here means a cap row was keyed to a branch the lines do not resolve to.

- [ ] **Step 9: Verify on v15**

```bash
cd /root/workspace/bench15
bench --site development.localhost run-tests --module asn_module.tests.test_stock_cap_fetch
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add asn_module/stock_cap/fetch.py asn_module/tests/test_stock_cap_fetch.py \
        asn_module/tests/test_stock_cap_api.py \
        asn_module/templates/pages/test_asn_new_services.py \
        asn_module/utils/cypress_helpers.py
git commit -m "feat: read stock cap ceilings from ASN Item Branch Cap"
```

---

### Task 4: Retire Item.custom_max_stock

**Files:**
- Delete: `asn_module/custom_fields/item.py`
- Delete: `asn_module/patches/create_item_max_stock_field.py`
- Create: `asn_module/patches/remove_item_max_stock_field.py`
- Modify: `asn_module/setup.py`
- Modify: `asn_module/patches.txt`
- Modify: `asn_module/tests/test_hooks.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. After this task no code references `custom_max_stock`.

- [ ] **Step 1: Write the failing test**

In `asn_module/tests/test_hooks.py`, delete `test_item_custom_fields_define_max_stock` and `test_item_max_stock_patch_is_registered_for_post_model_sync` entirely, and delete the `import asn_module.custom_fields.item as item_fields` line.

Update `test_after_install_sets_up_fields_notifications_and_actions` back to four setup functions — remove the `setup_item_fields` patch decorator, its parameter, its `side_effect`, its assertion, and `"item"` from the expected order:

```python
	@patch("asn_module.setup.setup_pi_fields")
	@patch("asn_module.setup.setup_pr_fields")
	@patch("asn_module.setup.create_notifications")
	@patch("asn_module.setup.register_actions")
	def test_after_install_sets_up_fields_notifications_and_actions(
		self,
		register_actions,
		create_notifications,
		setup_pr_fields,
		setup_pi_fields,
	):
		call_order = []
		setup_pr_fields.side_effect = lambda: call_order.append("pr")
		setup_pi_fields.side_effect = lambda: call_order.append("pi")
		create_notifications.side_effect = lambda: call_order.append("notif")
		register_actions.side_effect = lambda: call_order.append("actions")

		setup_module.after_install()

		setup_pr_fields.assert_called_once_with()
		setup_pi_fields.assert_called_once_with()
		create_notifications.assert_called_once_with()
		register_actions.assert_called_once_with()
		self.assertEqual(call_order, ["pr", "pi", "notif", "actions"])
```

Add a test that the removal patch is registered, replacing the create-patch test:

```python
	def test_item_max_stock_removal_patch_is_registered_for_post_model_sync(self):
		patches = (Path(__file__).resolve().parents[1] / "patches.txt").read_text()
		post_sync = patches.split("[post_model_sync]", 1)[1]

		self.assertIn("asn_module.patches.remove_item_max_stock_field", post_sync)
		self.assertNotIn("asn_module.patches.create_item_max_stock_field", post_sync)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_hooks --lightmode
```

Expected: FAIL — `patches.txt` still names the create patch, and `after_install` still calls `setup_item_fields`.

- [ ] **Step 3: Write the removal patch**

`asn_module/patches/remove_item_max_stock_field.py`:

```python
import frappe


def execute():
	"""Delete the retired Item.custom_max_stock custom field.

	Ceilings now live on ASN Item Branch Cap, keyed by (item, branch). Leaving the old
	field on the Item form would show a number that no longer affects anything, which is
	the failure this feature already hit once: a configured ceiling that silently did
	nothing and gave no signal why.
	"""
	name = frappe.db.get_value("Custom Field", {"dt": "Item", "fieldname": "custom_max_stock"})
	if name:
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
```

- [ ] **Step 4: Remove the field definition and its wiring**

```bash
git rm asn_module/custom_fields/item.py asn_module/patches/create_item_max_stock_field.py
```

In `asn_module/setup.py`, delete the `setup_item_fields` import line and its call, leaving:

```python
from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.notifications.setup import create_notifications
from asn_module.setup_actions import register_actions


def after_install():
	setup_pr_fields()
	setup_pi_fields()
	create_notifications()
	register_actions()
```

In `asn_module/patches.txt`, replace the create patch line under `[post_model_sync]`:

```
asn_module.patches.remove_item_max_stock_field
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.tests.test_hooks --lightmode
```

Expected: all PASS.

- [ ] **Step 6: Apply the patch to both benches and confirm the field is gone**

```bash
cd /root/workspace/bench16 && bench --site frappe16.localhost migrate
cd /root/workspace/bench15 && bench --site development.localhost migrate
```

Then confirm on each site:

```bash
cd /root/workspace/bench16/sites && ../env/bin/python -c "
import frappe; frappe.init(site='frappe16.localhost', sites_path='.'); frappe.connect()
print('custom field:', frappe.db.exists('Custom Field', {'dt':'Item','fieldname':'custom_max_stock'}))
print('column      :', frappe.db.has_column('Item','custom_max_stock'))"
```

Expected: `custom field: None`. The column may survive — Frappe does not always drop columns on custom field deletion — which is harmless because no code reads it.

- [ ] **Step 7: Confirm nothing references the retired field**

```bash
grep -rn "custom_max_stock" --include=*.py --include=*.js --include=*.json asn_module/ cypress/
```

Expected: exactly one match, in `asn_module/patches/remove_item_max_stock_field.py`. Task 3 already moved every test fixture onto cap rows, so any other match is a real leftover — fix it before committing.

- [ ] **Step 8: Commit**

```bash
ruff format asn_module/ && ruff check asn_module/
git add -u asn_module/setup.py asn_module/patches.txt asn_module/tests/test_hooks.py
git add asn_module/patches/remove_item_max_stock_field.py
git commit -m "feat: retire Item.custom_max_stock in favour of per-branch caps"
```

---

### Task 5: Full suite, e2e, and coverage gate

**Files:** none, unless a gap is found.

**Interfaces:**
- Consumes: every prior task.
- Produces: nothing.

- [ ] **Step 1: Run the full suite on v16 with coverage**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --app asn_module --coverage --lightmode
```

Expected: no failure that is not present on `main`. This bench carries pre-existing failures unrelated to this work; establish a baseline with `git stash` if the count is unclear, and compare failing test *identities*, not counts.

- [ ] **Step 2: Run every property module**

```bash
cd /root/workspace/bench16
for m in asn_module.property_tests.test_asn_new_services_properties \
         asn_module.property_tests.test_scan_code_properties \
         asn_module.property_tests.test_token_properties \
         asn_module.property_tests.test_stock_cap_properties; do
  HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests --module "$m" --lightmode
done
```

Expected: all PASS.

- [ ] **Step 3: Run the Cypress stock cap spec**

```bash
cd /root/workspace/bench16
E2E_SUITE=nightly bench run-ui-tests asn_module --headless --browser electron \
  --spec cypress/integration/nightly/stock_cap_e2e.js
```

Expected: 3 tests PASS. This proves the seeder's cap row drives real enforcement through the desk form.

- [ ] **Step 4: Check coverage of the changed code**

```bash
cd /root/workspace/bench16/sites
python3 -c "
import xml.etree.ElementTree as ET
r = ET.parse('coverage.xml').getroot()
for cls in r.iter('class'):
    fn = cls.get('filename') or ''
    if 'stock_cap' in fn or 'asn_item_branch_cap' in fn:
        ls = cls.find('lines').findall('line')
        cov = sum(1 for l in ls if int(l.get('hits')) > 0)
        miss = [l.get('number') for l in ls if int(l.get('hits')) == 0]
        print(f'{fn:70s} {cov}/{len(ls)}  missing: {miss or \"-\"}')
"
```

Any uncovered line in the new doctype controller or in `fetch.py`'s new query needs a real test. A defensive branch no caller can reach should be reported, not contorted into a test.

- [ ] **Step 5: Run pre-commit**

```bash
cd /root/workspace/asn_module
pre-commit run --all-files
```

Expected: all hooks pass.

- [ ] **Step 6: Commit any gap-closing tests**

```bash
git add -A asn_module/
git commit -m "test: close per-branch cap coverage gaps"
```

Skip this step if Step 4 found no gap.

---

## Deployment Note

Both benches need `bench migrate` (creates `ASN Item Branch Cap`, runs the removal patch) followed by `bench --site <site> clear-cache`.

A branch stays uncapped until an `ASN Item Branch Cap` row exists for it *and* an enabled `ASN Stock Cap Settings` names at least one warehouse. That is the documented fail-open behaviour; the doctype's save-time warning exists so nobody has to discover it by watching an over-cap ASN submit successfully.
