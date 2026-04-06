# Coverage Gap Closure — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve Python line coverage >= 95% for `asn_module` by configuring `coverage.py`, writing ~65-75 new unit tests across 11 modules, completing integration test tasks 2-3, and adding Cypress nightly E2E specs.

**Architecture:** Coverage tooling first (validate measurement works), then baseline measurement, then unit tests for untested modules (biggest coverage lift), then integration test completion, then Cypress E2E. Each chunk produces working, testable software independently.

**Tech Stack:** `coverage.py`, `FrappeTestCase`, `unittest.TestCase`, `bench run-tests --app asn_module`, Cypress, `cy.call` / `cy.request`

**Spec:** `docs/superpowers/specs/2026-04-05-coverage-gap-closure-design.md`

---

## File Map

| Path | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | **Modify** | Add `[tool.coverage.run]` and `[tool.coverage.report]` sections |
| `scripts/run_ephemeral_python_tests.sh` | **Modify** | Wrap `bench run-tests` with `coverage run` + emit report |
| `.github/workflows/ci.yml` | **Modify** | Upload `coverage.xml` as artifact |
| `asn_module/qr_engine/tests/test_scan_codes.py` | **Create** | Unit tests for `scan_codes.py` |
| `asn_module/tests/test_traceability.py` | **Create** | Unit tests for `traceability.py` |
| `asn_module/tests/test_transition_trace_report.py` | **Modify** | Extend with filter/limit tests |
| `asn_module/tests/test_commands.py` | **Create** | Unit tests for `commands.py` |
| `asn_module/handlers/tests/test_utils.py` | **Create** | Unit tests for `handlers/utils.py` |
| `asn_module/tests/test_setup_actions.py` | **Create** | Unit tests for `setup_actions.py` |
| `asn_module/templates/pages/test_asn.py` | **Modify** | Extend with incremental portal page tests |
| `asn_module/templates/pages/test_asn_new_services.py` | **Create** | Unit tests for `asn_new_services.py` (largest untested module) |
| `asn_module/templates/pages/test_asn_new.py` | **Modify** | Extend with incremental happy path tests |
| `asn_module/templates/pages/test_asn_new_search.py` | **Modify** | Extend with edge case tests |
| `asn_module/asn_module/doctype/asn/test_asn.py` | **Modify** | Real attachment context (Task 2) |
| `asn_module/tests/test_e2e_flow.py` | **Modify** | Remove `get_roles` patch (Task 3) |
| `cypress/integration/smoke/` | **Create dir** | Move existing smoke specs |
| `cypress/integration/nightly/asn_desk_nightly.js` | **Create** | API-seeded ASN desk E2E |
| `cypress/integration/nightly/scan_station_nightly.js` | **Create** | API-seeded scan station E2E |
| `cypress.config.cjs` | **Modify** | `specPattern` driven by `E2E_SUITE` env var |
| `scripts/run_ephemeral_e2e.sh` | **Modify** | Pass `E2E_SUITE` based on mode |

---

## Chunk 1: Coverage Tooling and Baseline

### Task 1: Configure coverage.py in pyproject.toml

**Files:**
- Modify: `pyproject.toml` (append after `[tool.ruff.format]` section, line 62)

- [ ] **Step 1: Add coverage configuration to pyproject.toml**

Append the following to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["asn_module"]
omit = [
	"*/tests/*",
	"*/patches/*",
	"*/config/*",
	"*/__init__.py",
	"asn_module/setup.py",
	"*/templates/pages/test_*.py",
]

[tool.coverage.report]
fail_under = 95
show_missing = true
skip_empty = true
exclude_lines = [
	"pragma: no cover",
	"if __name__ == .__main__.",
	"raise NotImplementedError",
]
```

- [ ] **Step 2: Verify TOML is valid**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"`
Expected: No output (valid TOML)

- [ ] **Step 3: Run ruff check (no Python changes, but verify)**

Run: `ruff check asn_module/`
Expected: No new errors

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add coverage.py configuration to pyproject.toml"
```

---

### Task 2: Integrate coverage into CI test script

**Files:**
- Modify: `scripts/run_ephemeral_python_tests.sh` (line 60-69)

- [ ] **Step 1: Modify the test invocation to use coverage run**

In `scripts/run_ephemeral_python_tests.sh`, replace lines 60-69:

**Old:**
```bash
run_tests_cmd=(bench --site "$SITE_NAME" run-tests --app asn_module)
if [ "${ERPNEXT_VERSION:-}" = "16" ]; then
	run_tests_cmd+=(--lightmode)
fi

if [ "$#" -gt 0 ]; then
	run_tests_cmd+=(--module "$1")
fi

"${run_tests_cmd[@]}"
```

**New:**
```bash
run_tests_cmd=("$(which bench)" --site "$SITE_NAME" run-tests --app asn_module)
if [ "${ERPNEXT_VERSION:-}" = "16" ]; then
	run_tests_cmd+=(--lightmode)
fi

if [ "$#" -gt 0 ]; then
	run_tests_cmd+=(--module "$1")
fi

coverage run "${run_tests_cmd[@]}"
coverage report
coverage xml -o coverage.xml
```

- [ ] **Step 2: Verify script syntax**

Run: `bash -n scripts/run_ephemeral_python_tests.sh`
Expected: No output (valid bash)

- [ ] **Step 3: Commit**

```bash
git add scripts/run_ephemeral_python_tests.sh
git commit -m "ci: integrate coverage.py into test runner script"
```

---

### Task 3: Upload coverage.xml as CI artifact

**Files:**
- Modify: `.github/workflows/ci.yml` (after "Run Tests" step, line 109)

- [ ] **Step 1: Add coverage artifact upload step**

Add after the "Run Tests" step in `.github/workflows/ci.yml`:

```yaml
      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
          if-no-files-found: warn
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: upload coverage.xml as workflow artifact"
```

---

### Task 4: Run baseline measurement (manual / documentation step)

This task documents the baseline. No code changes.

- [ ] **Step 1: Run coverage report locally**

On a running Frappe bench (see AGENTS.md for service startup):

```bash
cd /home/ubuntu/frappe-bench
export PATH="$HOME/.local/bin:$PATH"
coverage run $(which bench) --site dev.localhost run-tests --app asn_module --lightmode
coverage report
```

- [ ] **Step 2: Document baseline**

Record the output of `coverage report` in a comment on the PR or in a `docs/superpowers/coverage-baseline.md` file. This establishes which modules have the most uncovered lines and validates that the 95% target is reachable.

Expected: Coverage percentage and per-module breakdown printed to stdout.

---

## Chunk 2: Unit Tests for Pure Function Modules

### Task 5: Test `qr_engine/scan_codes.py` (12-15 tests)

**Files:**
- Create: `asn_module/qr_engine/tests/test_scan_codes.py`
- Source: `asn_module/qr_engine/scan_codes.py` (143 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/qr_engine/tests/test_scan_codes.py`:

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.qr_engine.scan_codes import (
	format_scan_code_for_display,
	get_or_create_scan_code,
	get_scan_code_doc,
	normalize_scan_code,
	record_successful_scan,
	validate_scan_code_row,
	verify_registry_row_points_to_existing_source,
)


class TestFormatScanCodeForDisplay(FrappeTestCase):
	def test_empty_code_returns_empty(self):
		self.assertEqual(format_scan_code_for_display(""), "")

	def test_short_code_unchanged(self):
		self.assertEqual(format_scan_code_for_display("AB"), "AB")

	def test_exact_group_length(self):
		self.assertEqual(format_scan_code_for_display("ABCD"), "ABCD")

	def test_long_code_grouped(self):
		result = format_scan_code_for_display("ABCDEFGHIJKLMNOP")
		self.assertEqual(result, "ABCD-EFGH-IJKL-MNOP")

	def test_odd_length_code(self):
		result = format_scan_code_for_display("ABCDEFGHI")
		self.assertEqual(result, "ABCD-EFGH-I")


class TestNormalizeScanCode(FrappeTestCase):
	def test_none_returns_empty(self):
		self.assertEqual(normalize_scan_code(None), "")

	def test_strips_dashes(self):
		self.assertEqual(normalize_scan_code("AB-CD-EF"), "ABCDEF")

	def test_strips_spaces(self):
		self.assertEqual(normalize_scan_code("AB CD EF"), "ABCDEF")

	def test_uppercases(self):
		self.assertEqual(normalize_scan_code("abcdef"), "ABCDEF")


class TestGetOrCreateScanCode(FrappeTestCase):
	def test_creates_new_scan_code(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-001")
		self.assertTrue(name)
		doc = frappe.get_doc("Scan Code", name)
		self.assertEqual(doc.action_key, "create_purchase_receipt")
		self.assertEqual(doc.source_doctype, "ASN")
		self.assertEqual(doc.source_name, "ASN-TEST-001")
		self.assertEqual(doc.status, "Active")

	def test_returns_existing_active(self):
		first = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-002")
		second = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-002")
		self.assertEqual(first, second)

	def test_rejects_empty_action_key(self):
		with self.assertRaises(frappe.ValidationError):
			get_or_create_scan_code("", "ASN", "ASN-TEST-003")


class TestGetScanCodeDoc(FrappeTestCase):
	def test_found(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-010")
		doc = get_scan_code_doc(name)
		self.assertIsNotNone(doc)
		self.assertEqual(doc.name, name)

	def test_not_found(self):
		result = get_scan_code_doc("NONEXISTENT-CODE")
		self.assertIsNone(result)

	def test_normalized_lookup(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", "ASN-TEST-011")
		doc = get_scan_code_doc(f"  {name[:4]}-{name[4:]}  ")
		self.assertIsNotNone(doc)


class TestValidateScanCodeRow(FrappeTestCase):
	def _make_scan_code_doc(self, status="Active", expires_on=None):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"ASN-VLD-{frappe.generate_hash(length=6)}")
		if status != "Active":
			frappe.db.set_value("Scan Code", name, "status", status, update_modified=False)
		if expires_on is not None:
			frappe.db.set_value("Scan Code", name, "expires_on", expires_on, update_modified=False)
		return frappe.get_doc("Scan Code", name)

	def test_active_ok(self):
		doc = self._make_scan_code_doc(status="Active")
		validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_blocked(self):
		doc = self._make_scan_code_doc(status="Used")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_used_rescan_safe_ok(self):
		doc = self._make_scan_code_doc(status="Used")
		validate_scan_code_row(doc, "confirm_putaway")

	def test_revoked_blocked(self):
		doc = self._make_scan_code_doc(status="Revoked")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_expired_blocked(self):
		doc = self._make_scan_code_doc(status="Expired")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")

	def test_expiry_date_in_past_blocked(self):
		doc = self._make_scan_code_doc(status="Active", expires_on="2000-01-01")
		with self.assertRaises(frappe.ValidationError):
			validate_scan_code_row(doc, "create_purchase_receipt")


class TestRecordSuccessfulScan(FrappeTestCase):
	def test_increments_count(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"ASN-REC-{frappe.generate_hash(length=6)}")
		record_successful_scan(name, "create_purchase_receipt")
		count = frappe.db.get_value("Scan Code", name, "scan_count")
		self.assertEqual(count, 1)

	def test_sets_used_for_non_rescan_safe(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"ASN-REC2-{frappe.generate_hash(length=6)}")
		record_successful_scan(name, "create_purchase_receipt")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Used")

	def test_stays_active_for_rescan_safe(self):
		name = get_or_create_scan_code("confirm_putaway", "ASN", f"ASN-REC3-{frappe.generate_hash(length=6)}")
		record_successful_scan(name, "confirm_putaway")
		status = frappe.db.get_value("Scan Code", name, "status")
		self.assertEqual(status, "Active")


class TestVerifyRegistryRowPointsToExistingSource(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from asn_module.utils.test_setup import before_tests
		before_tests()

	def test_valid_source_returns_true(self):
		from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		doc = frappe.get_doc("Scan Code", name)
		self.assertTrue(verify_registry_row_points_to_existing_source(doc))

	def test_missing_source_returns_false(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"NONEXISTENT-{frappe.generate_hash(length=6)}")
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))

	def test_missing_doctype_returns_false(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"ASN-VRFY2-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Scan Code", name, "source_doctype", "FakeDocType", update_modified=False)
		doc = frappe.get_doc("Scan Code", name)
		self.assertFalse(verify_registry_row_points_to_existing_source(doc))
```

- [ ] **Step 2: Run tests to verify they fail then pass**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_scan_codes --lightmode`
Expected: All tests pass (TDD green-first for DB tests; pure function tests verify immediately)

- [ ] **Step 3: Commit**

```bash
git add asn_module/qr_engine/tests/test_scan_codes.py
git commit -m "test(scan_codes): add unit tests for scan_codes module"
```

---

### Task 6: Test `traceability.py` (6-8 tests)

**Files:**
- Create: `asn_module/tests/test_traceability.py`
- Source: `asn_module/traceability.py` (107 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/tests/test_traceability.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.traceability import (
	_idempotency_key,
	emit_asn_item_transition,
	get_latest_transition_rows_for_asn,
)


class TestIdempotencyKey(FrappeTestCase):
	def test_deterministic(self):
		k1 = _idempotency_key("ASN-001", "ASN-ITEM-001", "Received", "Purchase Receipt", "PR-001")
		k2 = _idempotency_key("ASN-001", "ASN-ITEM-001", "Received", "Purchase Receipt", "PR-001")
		self.assertEqual(k1, k2)

	def test_varies_with_asn(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-001")
		k2 = _idempotency_key("ASN-002", "ITEM-1", "Received", "PR", "PR-001")
		self.assertNotEqual(k1, k2)

	def test_varies_with_state(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", None, None)
		k2 = _idempotency_key("ASN-001", "ITEM-1", "Submitted", None, None)
		self.assertNotEqual(k1, k2)

	def test_varies_with_ref_name(self):
		k1 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-001")
		k2 = _idempotency_key("ASN-001", "ITEM-1", "Received", "PR", "PR-002")
		self.assertNotEqual(k1, k2)


class TestEmitAsnItemTransition(FrappeTestCase):
	def test_creates_row(self):
		asn = f"ASN-TR-{frappe.generate_hash(length=6)}"
		name = emit_asn_item_transition(
			asn=asn,
			asn_item="ASN-ITEM-001",
			item_code="ITEM-001",
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-001",
		)
		self.assertTrue(name)
		doc = frappe.get_doc("ASN Transition Log", name)
		self.assertEqual(doc.asn, asn)
		self.assertEqual(doc.state, "Received")

	def test_deduplicates_on_replay(self):
		asn = f"ASN-TR-D-{frappe.generate_hash(length=6)}"
		first = emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			ref_doctype="ASN",
			ref_name=asn,
		)
		second = emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			ref_doctype="ASN",
			ref_name=asn,
		)
		self.assertIsNotNone(first)
		self.assertIsNone(second)

	def test_returns_none_on_empty_asn(self):
		result = emit_asn_item_transition(asn="", state="Submitted")
		self.assertIsNone(result)

	def test_different_ref_name_same_state_creates_new_row(self):
		asn = f"ASN-TR-RN-{frappe.generate_hash(length=6)}"
		first = emit_asn_item_transition(
			asn=asn,
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-001",
		)
		second = emit_asn_item_transition(
			asn=asn,
			state="Received",
			ref_doctype="Purchase Receipt",
			ref_name="PR-002",
		)
		self.assertIsNotNone(first)
		self.assertIsNotNone(second)
		self.assertNotEqual(first, second)


class TestGetLatestTransitionRowsForAsn(FrappeTestCase):
	def test_returns_latest_per_item(self):
		asn = f"ASN-LT-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-1",
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-1",
			state="Received",
		)
		emit_asn_item_transition(
			asn=asn,
			asn_item="ITEM-2",
			state="Submitted",
		)
		rows = get_latest_transition_rows_for_asn(asn)
		items = {row.asn_item for row in rows}
		self.assertEqual(len(rows), 2)
		self.assertIn("ITEM-1", items)
		self.assertIn("ITEM-2", items)

	def test_empty_asn_returns_empty(self):
		rows = get_latest_transition_rows_for_asn("")
		self.assertEqual(rows, [])

	def test_respects_limit(self):
		asn = f"ASN-LTL-{frappe.generate_hash(length=6)}"
		for i in range(5):
			emit_asn_item_transition(
				asn=asn,
				asn_item=f"LIMIT-ITEM-{i}",
				state="Submitted",
			)
		rows = get_latest_transition_rows_for_asn(asn, limit=3)
		self.assertLessEqual(len(rows), 3)
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_traceability --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/tests/test_traceability.py
git commit -m "test(traceability): add unit tests for traceability module"
```

---

### Task 7: Extend `test_transition_trace_report.py` (4-6 incremental tests)

**Files:**
- Modify: `asn_module/tests/test_transition_trace_report.py` (15 lines, 2 existing tests)
- Source: `asn_module/asn_module/report/asn_item_transition_trace/asn_item_transition_trace.py` (115 lines)

- [ ] **Step 1: Write the incremental tests**

Replace the entire content of `asn_module/tests/test_transition_trace_report.py` with:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace import execute
from asn_module.traceability import emit_asn_item_transition


class TestAsnItemTransitionTraceReport(FrappeTestCase):
	def test_execute_returns_columns_and_rows_without_filters(self):
		columns, rows = execute({})
		self.assertEqual(len(columns), 10)
		self.assertIsInstance(rows, list)

	def test_execute_respects_limit(self):
		_, rows = execute({"limit_page_length": 5, "limit_start": 0})
		self.assertLessEqual(len(rows), 5)

	def test_filter_by_item_code(self):
		asn = f"ASN-RPT-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			item_code="FILTER-ITEM-001",
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			item_code="FILTER-ITEM-002",
			state="Submitted",
		)
		_, rows = execute({"item_code": "FILTER-ITEM-001"})
		for row in rows:
			self.assertEqual(row[3], "FILTER-ITEM-001")

	def test_filter_by_state(self):
		asn = f"ASN-RPT-ST-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
		)
		emit_asn_item_transition(
			asn=asn,
			state="Received",
		)
		_, rows = execute({"state": "Submitted"})
		for row in rows:
			self.assertEqual(row[4], "Submitted")

	def test_failures_only_filter(self):
		asn = f"ASN-RPT-FO-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			transition_status="OK",
		)
		emit_asn_item_transition(
			asn=asn,
			state="Received",
			transition_status="Error",
		)
		_, rows = execute({"failures_only": True})
		for row in rows:
			self.assertEqual(row[5], "Error")

	def test_search_text_filter(self):
		asn = f"ASN-RPT-SR-{frappe.generate_hash(length=6)}"
		emit_asn_item_transition(
			asn=asn,
			state="Submitted",
			details="unique_search_marker_xyz",
		)
		_, rows = execute({"search": "unique_search_marker_xyz"})
		self.assertTrue(any("unique_search_marker_xyz" in str(row) for row in rows))

	def test_limit_clamped_to_500(self):
		columns, rows = execute({"limit_page_length": 999})
		self.assertLessEqual(len(rows), 500)

	def test_limit_clamped_to_1_minimum(self):
		columns, rows = execute({"limit_page_length": 0})
		self.assertLessEqual(len(rows), 1)
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_transition_trace_report --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/tests/test_transition_trace_report.py
git commit -m "test(report): add filter and limit clamping tests for transition trace report"
```

---

## Chunk 3: Unit Tests for DB Modules and Portal Pages

### Task 8: Test `commands.py` (5-6 tests)

**Files:**
- Create: `asn_module/tests/test_commands.py`
- Source: `asn_module/commands.py` (97 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/tests/test_commands.py`:

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.commands import verify_qr_action_registry, verify_scan_code_registry
from asn_module.qr_engine.scan_codes import get_or_create_scan_code
from asn_module.setup_actions import register_actions


class TestVerifyScanCodeRegistry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from asn_module.utils.test_setup import before_tests
		before_tests()

	def test_all_valid_returns_ok(self):
		from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order, make_test_asn
		po = create_purchase_order(qty=10)
		asn = make_test_asn(purchase_order=po, qty=10)
		asn.insert(ignore_permissions=True)
		get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
		with patch("asn_module.commands.frappe.has_permission", return_value=True):
			result = verify_scan_code_registry()
		scan_code_orphans = [o for o in result.get("orphans", []) if o.get("source_name") == asn.name]
		self.assertEqual(len(scan_code_orphans), 0)

	def test_orphan_scan_code_returns_not_ok(self):
		name = get_or_create_scan_code("create_purchase_receipt", "ASN", f"ORPHAN-CMD-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Scan Code", name, "source_name", "NONEXISTENT-DOC-XYZ", update_modified=False)
		with patch("asn_module.commands.frappe.has_permission", return_value=True):
			result = verify_scan_code_registry()
		self.assertFalse(result["ok"])
		self.assertGreater(result["orphan_count"], 0)

	def test_permission_check(self):
		with (
			patch("asn_module.commands.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			verify_scan_code_registry()


class TestVerifyQrActionRegistry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		register_actions()

	def test_all_canonical_actions_present_returns_ok(self):
		result = verify_qr_action_registry()
		self.assertTrue(result["ok"])
		self.assertEqual(result["missing"], [])
		self.assertEqual(result["mismatched"], [])

	def test_missing_action_detected(self):
		reg = frappe.get_single("QR Action Registry")
		saved_actions = list(reg.actions)
		reg.actions = [row for row in saved_actions if row.action_key != "confirm_putaway"]
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertIn("confirm_putaway", result["missing"])
		finally:
			reg.actions = saved_actions
			reg.save(ignore_permissions=True)

	def test_mismatched_handler_detected(self):
		reg = frappe.get_single("QR Action Registry")
		saved_actions = list(reg.actions)
		for row in reg.actions:
			if row.action_key == "confirm_putaway":
				row.handler_method = "wrong.handler.path"
				break
		reg.save(ignore_permissions=True)
		try:
			result = verify_qr_action_registry()
			self.assertFalse(result["ok"])
			self.assertTrue(any(m["action_key"] == "confirm_putaway" for m in result["mismatched"]))
		finally:
			reg.actions = saved_actions
			reg.save(ignore_permissions=True)
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_commands --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/tests/test_commands.py
git commit -m "test(commands): add unit tests for verify_scan_code_registry and verify_qr_action_registry"
```

---

### Task 9: Test `handlers/utils.py` (3 tests)

**Files:**
- Create: `asn_module/handlers/tests/test_utils.py`
- Source: `asn_module/handlers/utils.py` (17 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/handlers/tests/test_utils.py`:

```python
import base64

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.handlers.utils import attach_qr_to_doc


class TestAttachQrToDoc(FrappeTestCase):
	def test_creates_file_attached_to_target(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": f"ATT-TEST-{frappe.generate_hash(length=6)}",
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		minimal_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
		qr_result = {"image_base64": minimal_png}
		attach_qr_to_doc(asn, qr_result, "qr")

		files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "ASN",
				"attached_to_name": asn.name,
			},
			fields=["name", "file_name"],
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0]["file_name"].startswith("qr-"))

	def test_invalid_base64_raises_error(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": f"ATT-BAD-{frappe.generate_hash(length=6)}",
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		with self.assertRaises(Exception):
			attach_qr_to_doc(asn, {"image_base64": "not-valid-base64!!!"}, "qr")

	def test_missing_image_base64_raises_key_error(self):
		asn = frappe.get_doc(
			{
				"doctype": "ASN",
				"supplier": "_Test ASN Supplier",
				"supplier_invoice_no": f"ATT-NOKEY-{frappe.generate_hash(length=6)}",
				"supplier_invoice_date": frappe.utils.today(),
				"expected_delivery_date": frappe.utils.today(),
				"items": [],
			}
		)
		asn.flags.ignore_permissions = True
		asn.insert(ignore_permissions=True)

		with self.assertRaises(KeyError):
			attach_qr_to_doc(asn, {}, "qr")
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_utils --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/handlers/tests/test_utils.py
git commit -m "test(handlers): add unit tests for attach_qr_to_doc"
```

---

### Task 10: Test `setup_actions.py` (2-3 tests)

**Files:**
- Create: `asn_module/tests/test_setup_actions.py`
- Source: `asn_module/setup_actions.py` (71 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/tests/test_setup_actions.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.setup_actions import get_canonical_actions, register_actions


class TestRegisterActions(FrappeTestCase):
	def test_register_actions_creates_all_seven(self):
		register_actions()
		reg = frappe.get_single("QR Action Registry")
		action_keys = [row.action_key for row in reg.actions]
		canonical_keys = [a["action_key"] for a in get_canonical_actions()]
		self.assertEqual(sorted(action_keys), sorted(canonical_keys))
		self.assertEqual(len(action_keys), 7)

	def test_idempotent_no_duplicates(self):
		register_actions()
		register_actions()
		reg = frappe.get_single("QR Action Registry")
		action_keys = [row.action_key for row in reg.actions]
		self.assertEqual(len(action_keys), len(set(action_keys)))

	def test_each_action_maps_to_importable_handler(self):
		from importlib import import_module

		for action in get_canonical_actions():
			parts = action["handler_method"].rsplit(".", 1)
			self.assertEqual(len(parts), 2, f"Invalid handler path: {action['handler_method']}")
			mod = import_module(parts[0])
			self.assertTrue(hasattr(mod, parts[1]), f"Handler not found: {action['handler_method']}")
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_setup_actions --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/tests/test_setup_actions.py
git commit -m "test(setup_actions): add unit tests for register_actions"
```

---

### Task 11: Test `asn_new_services.py` (15-20 tests) — Largest untested module

**Files:**
- Create: `asn_module/templates/pages/test_asn_new_services.py`
- Source: `asn_module/templates/pages/asn_new_services.py` (404 lines)

- [ ] **Step 1: Write the failing test file**

Create `asn_module/templates/pages/test_asn_new_services.py`:

```python
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from asn_module.templates.pages.asn_new_services import (
	ParsedBulkRow,
	PortalValidationError,
	enforce_bulk_limits,
	normalize_group_field,
	normalize_group_value,
	parse_non_negative_rate,
	parse_optional_non_negative_rate,
	parse_positive_qty,
	parse_required_supplier_invoice_amount,
	validate_bulk_group_count,
	validate_invoice_group_consistency,
	validate_qty_within_remaining,
	validate_selected_purchase_orders,
)


class TestParsePositiveQty(FrappeTestCase):
	def test_positive(self):
		self.assertEqual(parse_positive_qty("10", row_number=1, field="qty"), 10.0)

	def test_zero_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("0", row_number=1, field="qty")

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("-5", row_number=1, field="qty")

	def test_empty_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty("", row_number=1, field="qty")


class TestParseNonNegativeRate(FrappeTestCase):
	def test_zero_ok(self):
		self.assertEqual(parse_non_negative_rate("0", row_number=1, field="rate"), 0.0)

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_non_negative_rate("-1", row_number=1, field="rate")

	def test_valid_returns_float(self):
		self.assertEqual(parse_non_negative_rate("25.5", row_number=1, field="rate"), 25.5)


class TestParseOptionalNonNegativeRate(FrappeTestCase):
	def test_none_returns_none(self):
		self.assertIsNone(parse_optional_non_negative_rate(None, row_number=1, field="rate"))

	def test_empty_returns_none(self):
		self.assertIsNone(parse_optional_non_negative_rate("", row_number=1, field="rate"))

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_optional_non_negative_rate("-1", row_number=1, field="rate")

	def test_valid_returns_float(self):
		self.assertEqual(parse_optional_non_negative_rate("10", row_number=1, field="rate"), 10.0)


class TestParseRequiredSupplierInvoiceAmount(FrappeTestCase):
	def test_valid(self):
		self.assertEqual(
			parse_required_supplier_invoice_amount("250", row_number=1), 250.0
		)

	def test_zero_ok(self):
		self.assertEqual(
			parse_required_supplier_invoice_amount("0", row_number=1), 0.0
		)

	def test_negative_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_required_supplier_invoice_amount("-10", row_number=1)

	def test_empty_raises(self):
		with self.assertRaises(PortalValidationError):
			parse_required_supplier_invoice_amount("", row_number=1)


class TestNormalizeGroupValue(FrappeTestCase):
	def test_whitespace(self):
		self.assertEqual(normalize_group_value("  hello  "), "hello")

	def test_none(self):
		self.assertEqual(normalize_group_value(None), "")

	def test_normal(self):
		self.assertEqual(normalize_group_value("hello"), "hello")


class TestNormalizeGroupField(FrappeTestCase):
	def test_supplier_invoice_amount_numeric(self):
		result = normalize_group_field("supplier_invoice_amount", "100.00")
		self.assertEqual(result, "100.0")

	def test_supplier_invoice_amount_empty(self):
		result = normalize_group_field("supplier_invoice_amount", "")
		self.assertEqual(result, "")

	def test_other_field(self):
		result = normalize_group_field("lr_no", "  LR123  ")
		self.assertEqual(result, "LR123")


class TestEnforceBulkLimits(FrappeTestCase):
	def test_within_limit_ok(self):
		rows = [SimpleNamespace()] * 10
		enforce_bulk_limits(rows)

	def test_over_limit_raises(self):
		from asn_module.templates.pages.asn_new_services import MAX_BULK_ROWS

		rows = [SimpleNamespace()] * (MAX_BULK_ROWS + 1)
		with self.assertRaises(PortalValidationError):
			enforce_bulk_limits(rows)


class TestValidateBulkGroupCount(FrappeTestCase):
	def test_within_limit_ok(self):
		groups = {f"INV-{i}": [] for i in range(10)}
		validate_bulk_group_count(groups)

	def test_exceeds_raises(self):
		from asn_module.templates.pages.asn_new_services import MAX_BULK_INVOICES

		groups = {f"INV-{i}": [] for i in range(MAX_BULK_INVOICES + 1)}
		with self.assertRaises(PortalValidationError):
			validate_bulk_group_count(groups)


class TestValidateInvoiceGroupConsistency(FrappeTestCase):
	def _make_bulk_row(self, **overrides):
		defaults = dict(
			row_number=1,
			supplier_invoice_no="INV-1",
			supplier_invoice_date="2026-04-05",
			expected_delivery_date="2026-04-06",
			lr_no="",
			lr_date="",
			transporter_name="",
			vehicle_number="",
			driver_contact="",
			supplier_invoice_amount=100.0,
			purchase_order="PO-001",
			sr_no="1",
			item_code="ITEM-001",
			qty=10.0,
			rate=25.0,
		)
		defaults.update(overrides)
		return ParsedBulkRow(**defaults)

	def test_matching_group_ok(self):
		rows = [
			self._make_bulk_row(row_number=1),
			self._make_bulk_row(row_number=2),
		]
		validate_invoice_group_consistency("INV-1", rows)

	def test_field_mismatch_raises(self):
		rows = [
			self._make_bulk_row(row_number=1, lr_no="LR-001"),
			self._make_bulk_row(row_number=2, lr_no="LR-002"),
		]
		with self.assertRaises(PortalValidationError):
			validate_invoice_group_consistency("INV-1", rows)


class TestValidateQtyWithinRemaining(FrappeTestCase):
	def test_within_limit_ok(self):
		validate_qty_within_remaining(
			purchase_order_item="POI-001",
			qty=5,
			row_number=1,
			invoice_no="INV-1",
			remaining_qty_by_name={"POI-001": 10},
		)

	def test_exactly_at_limit_ok(self):
		validate_qty_within_remaining(
			purchase_order_item="POI-001",
			qty=10,
			row_number=1,
			invoice_no="INV-1",
			remaining_qty_by_name={"POI-001": 10},
		)

	def test_over_limit_raises(self):
		with self.assertRaises(PortalValidationError):
			validate_qty_within_remaining(
				purchase_order_item="POI-001",
				qty=15,
				row_number=1,
				invoice_no="INV-1",
				remaining_qty_by_name={"POI-001": 10},
			)


class TestValidateSelectedPurchaseOrders(FrappeTestCase):
	def test_empty_list_raises(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_services.get_supplier_open_purchase_orders",
				return_value={},
			),
			self.assertRaises(PortalValidationError),
		):
			validate_selected_purchase_orders(supplier="Supp-001", selected_purchase_orders=[])

	def test_invalid_po_raises(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_services.get_supplier_open_purchase_orders",
				return_value={"PO-0001": SimpleNamespace(name="PO-0001")},
			),
			self.assertRaises(PortalValidationError),
		):
			validate_selected_purchase_orders(
				supplier="Supp-001",
				selected_purchase_orders=["PO-0001", "PO-INVALID"],
			)
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_services --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/templates/pages/test_asn_new_services.py
git commit -m "test(portal): add unit tests for asn_new_services parsing and validation"
```

---

### Task 12: Extend `test_asn_new.py` (4-6 incremental tests)

**Files:**
- Modify: `asn_module/templates/pages/test_asn_new.py` (309 lines, 14 existing tests)
- Source: `asn_module/templates/pages/asn_new.py` (527 lines)

- [ ] **Step 1: Add incremental tests to `test_asn_new.py`**

First, add `import frappe` to the file's imports (it is not currently imported — the file only imports `ValidationError as FrappeValidationError`).

Then append the following tests to the `TestASNNewPortalPage` class in `asn_module/templates/pages/test_asn_new.py`:

```python
	def test_get_context_returns_early_on_get(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="GET", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value="Supp-001"),
			patch(
				"asn_module.templates.pages.asn_new.get_open_purchase_orders_for_supplier", return_value=[]
			),
		):
			asn_new.get_context(context)
		self.assertEqual(context.title, "New ASN")
		self.assertEqual(context.single_errors, [])

	def test_request_supplier_invoice_amount_valid(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": "100"}),
		):
			result = asn_new._request_supplier_invoice_amount()
		self.assertEqual(result, 100.0)

	def test_request_supplier_invoice_amount_negative_raises(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": "-10"}),
			self.assertRaises(PortalValidationError),
		):
			asn_new._request_supplier_invoice_amount()

	def test_request_supplier_invoice_amount_empty_raises(self):
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", SimpleNamespace()),
			patch("asn_module.templates.pages.asn_new.frappe.form_dict", {"supplier_invoice_amount": ""}),
			self.assertRaises(PortalValidationError),
		):
			asn_new._request_supplier_invoice_amount()

	def test_default_asn_route_format(self):
		route = asn_new._default_asn_route("ASN-001")
		self.assertTrue(route.startswith("asn/"))

	def test_get_context_rejects_non_supplier(self):
		context = SimpleNamespace()
		request = SimpleNamespace(method="GET", files={})
		with (
			patch("asn_module.templates.pages.asn_new.frappe.request", request),
			patch(
				"asn_module.templates.pages.asn_new.frappe.session",
				SimpleNamespace(user="non-supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new._get_supplier_for_user", return_value=None),
			self.assertRaises(frappe.PermissionError),
		):
			asn_new.get_context(context)
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/templates/pages/test_asn_new.py
git commit -m "test(portal): add incremental tests for asn_new get_context and request helpers"
```

---

### Task 13: Extend `test_asn_new_search.py` (2-3 incremental tests)

**Files:**
- Modify: `asn_module/templates/pages/test_asn_new_search.py` (79 lines, 3 existing tests)
- Source: `asn_module/templates/pages/asn_new_search.py` (63 lines)

- [ ] **Step 1: Add incremental tests**

Append the following tests to the `TestASNNewSearch` class in `asn_module/templates/pages/test_asn_new_search.py`:

```python
	def test_get_supplier_raises_when_none(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="no-supplier@example.com"),
			),
			patch("asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value=None),
			self.assertRaises(frappe.PermissionError),
		):
			asn_new_search._get_supplier()

	def test_search_open_purchase_orders_empty_txt_returns_all(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(name="PO-0001", status="To Receive", transaction_date="2026-04-05"),
					SimpleNamespace(name="PO-0002", status="To Receive", transaction_date="2026-04-06"),
				],
			),
		):
			rows = asn_new_search.search_open_purchase_orders(txt="")
		self.assertEqual(len(rows), 2)

	def test_search_purchase_order_items_with_txt_filter(self):
		with (
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.session",
				SimpleNamespace(user="s@example.com"),
			),
			patch(
				"asn_module.templates.pages.asn_new_search._get_supplier_for_user", return_value="Supp-001"
			),
			patch(
				"asn_module.templates.pages.asn_new_search.get_open_purchase_orders_for_supplier",
				return_value=[
					SimpleNamespace(name="PO-0001", status="To Receive", transaction_date="2026-04-05")
				],
			),
			patch(
				"asn_module.templates.pages.asn_new_search.frappe.get_all",
				return_value=[
					SimpleNamespace(name="POI-1", idx=1, item_code="ITEM-001", uom="Nos", rate=10),
					SimpleNamespace(name="POI-2", idx=2, item_code="OTHER-002", uom="Nos", rate=20),
				],
			),
		):
			rows = asn_new_search.search_purchase_order_items(purchase_order="PO-0001", txt="ITEM")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["value"], "ITEM-001")
```

- [ ] **Step 2: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_search --lightmode`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add asn_module/templates/pages/test_asn_new_search.py
git commit -m "test(portal): add incremental tests for asn_new_search edge cases"
```

---

### Task 14: Review `asn.py` portal page coverage (0-3 incremental tests)

**Files:**
- Modify: `asn_module/templates/pages/test_asn.py` (288 lines, 15 existing tests)
- Source: `asn_module/templates/pages/asn.py` (186 lines)

- [ ] **Step 1: Check baseline coverage for `asn.py`**

After running the baseline measurement (Task 4), check if `asn.py` has uncovered branches. The existing 15 tests are thorough. If coverage is already >= 95% for this file, skip to Step 3.

If uncovered branches remain in `_ensure_asn_route` or `get_open_purchase_orders_for_supplier`, add targeted tests.

- [ ] **Step 2: Add incremental tests (only if needed)**

Only add tests for specific uncovered branches identified in Step 1. Example test for `get_open_purchase_orders_for_supplier` with empty supplier:

```python
	def test_get_open_purchase_orders_returns_empty_for_empty_supplier(self):
		from asn_module.templates.pages.asn import get_open_purchase_orders_for_supplier
		result = get_open_purchase_orders_for_supplier("")
		self.assertEqual(result, [])
```

- [ ] **Step 3: Commit (only if tests were added)**

```bash
git add asn_module/templates/pages/test_asn.py
git commit -m "test(portal): add incremental tests for asn.py uncovered branches"
```

---

## Chunk 4: Integration Test Completion and Cypress E2E

### Task 15: Real attachment context (Integration Task 2)

**Files:**
- Modify: `asn_module/asn_module/doctype/asn/test_asn.py` (line 215-218, `real_asn_attachment_context`)

The current `real_asn_attachment_context()` is a no-op (`yield` only). Per the existing plan, it should use real `generate_qr` / `generate_barcode` / `save_file`.

- [ ] **Step 1: Verify real_asn_attachment_context works as-is**

The current implementation:
```python
@contextmanager
def real_asn_attachment_context():
    """Use real ``generate_qr`` / ``generate_barcode`` / ``save_file`` on ASN submit (no mocks)."""
    yield
```

This already works because `test_e2e_flow.py` and `dispatch_flow.py` use it successfully — they submit ASNs with real QR/barcode generation and real file saves. The no-op context manager is correct: it simply doesn't mock anything.

Verify by running:
```bash
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_e2e_flow --lightmode
```

Expected: Both tests pass (already using real attachments).

- [ ] **Step 2: If barcode libs fail, add narrow patch**

If Step 1 fails with barcode library errors, modify `real_asn_attachment_context` to patch only `generate_barcode`:

```python
@contextmanager
def real_asn_attachment_context():
    """Use real ``generate_qr`` / ``save_file`` on ASN submit.

    ``generate_barcode`` is patched to return minimal valid PNG bytes
    when python-barcode is unavailable in CI.
    """
    try:
        from asn_module.qr_engine.generate import generate_barcode
        yield
    except (ImportError, Exception):
        from unittest.mock import patch

        def _fake_barcode(*args, **kwargs):
            import base64
            return {"image_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()}

        with patch("asn_module.asn_module.doctype.asn.asn.generate_barcode", side_effect=_fake_barcode):
            yield
```

- [ ] **Step 3: Commit (only if changes were made)**

```bash
git add asn_module/asn_module/doctype/asn/test_asn.py
git commit -m "test(asn): harden real_asn_attachment_context for CI barcode fallback"
```

---

### Task 16: Remove `get_roles` patch from `test_e2e_flow` (Integration Task 3)

**Files:**
- Modify: `asn_module/tests/test_e2e_flow.py` (103 lines)

The current `test_e2e_flow.py` already uses `ensure_integration_user` and `integration_user_context` (see lines 13, 39). There is no `get_roles` patch in the current code. This task was already completed in a prior implementation.

- [ ] **Step 1: Verify no `get_roles` patches remain**

Run: `grep -n "get_roles" asn_module/tests/test_e2e_flow.py`
Expected: No output (no patches found)

- [ ] **Step 2: Run e2e flow tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_e2e_flow --lightmode`
Expected: Both tests pass

- [ ] **Step 3: Mark task as complete (no changes needed)**

---

### Task 17: Cypress — restructure spec directories

**Files:**
- Create: `cypress/integration/smoke/` directory
- Create: `cypress/integration/nightly/` directory
- Move: `cypress/integration/asn_desk_smoke.js` → `cypress/integration/smoke/asn_desk_smoke.js`
- Move: `cypress/integration/scan_station_smoke.js` → `cypress/integration/smoke/scan_station_smoke.js`
- Modify: `cypress.config.cjs`

- [ ] **Step 1: Create directories and move smoke specs**

```bash
mkdir -p cypress/integration/smoke
mkdir -p cypress/integration/nightly
mv cypress/integration/asn_desk_smoke.js cypress/integration/smoke/asn_desk_smoke.js
mv cypress/integration/scan_station_smoke.js cypress/integration/smoke/scan_station_smoke.js
```

- [ ] **Step 2: Update cypress.config.cjs for E2E_SUITE support**

Replace the `specPattern` line in `cypress.config.cjs` (line 34):

**Old:**
```javascript
    specPattern: "cypress/integration/**/*.js",
```

**New:**
```javascript
    specPattern: (() => {
      const suite = process.env.E2E_SUITE || "smoke";
      if (suite === "nightly") return "cypress/integration/nightly/**/*.js";
      if (suite === "all") return "cypress/integration/**/*.js";
      return "cypress/integration/smoke/**/*.js";
    })(),
```

- [ ] **Step 3: Update run_ephemeral_e2e.sh to pass E2E_SUITE**

In `scripts/run_ephemeral_e2e.sh`, replace the `case` block (lines 118-125):

**Old:**
```bash
case "$E2E_MODE" in
smoke | ci)
	bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron
	;;
*)
	echo "Unknown mode: $E2E_MODE (use smoke or ci)" >&2
	exit 1
	;;
esac
```

**New:**
```bash
case "$E2E_MODE" in
smoke)
	E2E_SUITE=smoke bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron
	;;
ci)
	E2E_SUITE=nightly bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron
	;;
*)
	echo "Unknown mode: $E2E_MODE (use smoke or ci)" >&2
	exit 1
	;;
esac
```

- [ ] **Step 4: Verify smoke specs still work locally**

Run: `E2E_SUITE=smoke npx cypress run --headless` (or via bench)
Expected: Smoke specs pass

- [ ] **Step 5: Commit**

```bash
git add cypress/ cypress.config.cjs scripts/run_ephemeral_e2e.sh
git commit -m "ci(cypress): restructure specs into smoke/ and nightly/ with E2E_SUITE support"
```

---

### Task 18: Cypress nightly spec — ASN desk

**Files:**
- Create: `cypress/integration/nightly/asn_desk_nightly.js`

- [ ] **Step 1: Create server-side test helper**

Create `asn_module/utils/cypress_helpers.py`:

```python
import frappe


@frappe.whitelist()
def seed_minimal_asn():
	"""Create and submit a minimal ASN for nightly Cypress E2E. Gated behind allow_tests."""
	if not frappe.conf.get("allow_tests"):
		frappe.throw("Only available in test mode")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)

	po = create_purchase_order(qty=10)
	asn = make_test_asn(
		purchase_order=po,
		supplier_invoice_no=f"NIGHTLY-{frappe.generate_hash(length=8)}",
		qty=10,
	)
	asn.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()

	return {"asn_name": asn.name, "asn_status": asn.status, "supplier": asn.supplier}
```

- [ ] **Step 2: Write the nightly ASN desk spec**

Create `cypress/integration/nightly/asn_desk_nightly.js`:

```javascript
const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN desk nightly", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call("asn_module.utils.cypress_helpers.seed_minimal_asn").then((result) => {
			seededData = result.message || result;
		});
	});

	it("shows seeded ASN in the ASN list view", () => {
		cy.visit(route("asn"));
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
		cy.get(".list-row", { timeout: 15000 }).should("contain.text", seededData.asn_name);
	});

	it("opens ASN detail and shows key fields", () => {
		cy.visit(route("Form/ASN/" + seededData.asn_name));
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		cy.get(".frappe-control[data-fieldname='supplier']", { timeout: 15000 }).should("exist");
	});
});
```

- [ ] **Step 3: Run nightly spec locally**

Run: `E2E_SUITE=nightly npx cypress run --spec "cypress/integration/nightly/asn_desk_nightly.js" --headless`
Expected: Spec passes

- [ ] **Step 4: Commit**

```bash
git add asn_module/utils/cypress_helpers.py cypress/integration/nightly/asn_desk_nightly.js
git commit -m "test(cypress): add nightly ASN desk E2E spec with API seeding"
```

---

### Task 19: Cypress nightly spec — Scan Station

**Files:**
- Create: `cypress/integration/nightly/scan_station_nightly.js`
- Modify: `asn_module/utils/cypress_helpers.py` (add scan station helper)

- [ ] **Step 1: Add scan station seeding helper**

Append to `asn_module/utils/cypress_helpers.py`:

```python
@frappe.whitelist()
def seed_scan_station_context():
	"""Create a submitted ASN with scan code for nightly Scan Station E2E."""
	if not frappe.conf.get("allow_tests"):
		frappe.throw("Only available in test mode")

	from asn_module.asn_module.doctype.asn.test_asn import (
		create_purchase_order,
		make_test_asn,
		real_asn_attachment_context,
	)
	from asn_module.qr_engine.scan_codes import get_or_create_scan_code
	from asn_module.setup_actions import register_actions

	register_actions()

	po = create_purchase_order(qty=10)
	asn = make_test_asn(
		purchase_order=po,
		supplier_invoice_no=f"SCAN-{frappe.generate_hash(length=8)}",
		qty=10,
	)
	asn.insert(ignore_permissions=True)
	with real_asn_attachment_context():
		asn.submit()

	scan_code_name = get_or_create_scan_code("create_purchase_receipt", "ASN", asn.name)
	scan_code_value = frappe.db.get_value("Scan Code", scan_code_name, "scan_code")

	return {
		"asn_name": asn.name,
		"scan_code": scan_code_value,
		"scan_code_name": scan_code_name,
	}
```

- [ ] **Step 2: Write the nightly Scan Station spec**

Create `cypress/integration/nightly/scan_station_nightly.js`:

```javascript
const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Scan Station nightly", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call("asn_module.utils.cypress_helpers.seed_scan_station_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("renders scan input", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
	});

	it("accepts scan code and shows success or expected feedback", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type(seededData.scan_code + "{enter}");
		cy.get(".scan-result, .scan-success, .scan-error", { timeout: 20000 }).should("be.visible");
	});
});
```

- [ ] **Step 3: Run nightly scan station spec**

Run: `E2E_SUITE=nightly npx cypress run --spec "cypress/integration/nightly/scan_station_nightly.js" --headless`
Expected: Spec passes

- [ ] **Step 4: Commit**

```bash
git add asn_module/utils/cypress_helpers.py cypress/integration/nightly/scan_station_nightly.js
git commit -m "test(cypress): add nightly Scan Station E2E spec with API seeding"
```

---

### Task 20: Final verification — coverage report

This task verifies all acceptance criteria from the spec.

- [ ] **Step 1: Run full test suite with coverage**

```bash
cd /home/ubuntu/frappe-bench
export PATH="$HOME/.local/bin:$PATH"
coverage run $(which bench) --site dev.localhost run-tests --app asn_module --lightmode
coverage report
```

Expected: `fail_under=95` passes. If it doesn't, identify remaining uncovered modules from the `show_missing = true` output and add targeted tests.

- [ ] **Step 2: Run linting**

```bash
cd /workspace
ruff check asn_module/
npx eslint asn_module/ --quiet
```

Expected: No errors

- [ ] **Step 3: Verify no `get_roles` patches on golden-path tests**

Run: `grep -rn "get_roles" asn_module/tests/test_e2e_flow.py`
Expected: No output

- [ ] **Step 4: Verify Cypress nightly specs pass**

```bash
E2E_SUITE=nightly bench --site dev.localhost run-ui-tests asn_module --headless --browser electron
```

Expected: Both nightly specs pass

- [ ] **Step 5: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore: final lint fixes and coverage gap closure"
```

---

## Verification Commands

```bash
# Full Python test suite with coverage
coverage run $(which bench) --site dev.localhost run-tests --app asn_module --lightmode
coverage report

# Individual module tests
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_scan_codes --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_traceability --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_transition_trace_report --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_commands --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_utils --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.test_setup_actions --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_services --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_search --lightmode

# Lint
ruff check asn_module/
npx eslint asn_module/ --quiet

# Cypress nightly
E2E_SUITE=nightly npx cypress run --headless

# Cypress smoke
E2E_SUITE=smoke npx cypress run --headless
```
