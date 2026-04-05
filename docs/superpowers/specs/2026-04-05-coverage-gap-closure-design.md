# Coverage Gap Closure — Design Specification

**Status:** Approved (brainstorming session, 2026-04-05)
**Target:** Python line coverage >= 95% via `coverage.py`
**Approach:** Coverage tooling first, then unit tests for gaps, then integration test completion, then Cypress E2E

---

## 1. Goals

- Configure `coverage.py` to measure Python line coverage for `asn_module` in CI and locally.
- **Measure baseline** before writing new tests to validate the 95% target is reachable.
- Add direct unit tests for 11 modules with coverage gaps (~65-75 new test methods).
- Complete remaining realistic integration test tasks (Tasks 2-3 from `2026-04-04-realistic-integration-tests-design.md`).
- Implement Cypress API-backed nightly E2E specs (per `2026-04-04-cypress-api-backed-e2e-design.md`).

---

## 2. Non-goals

- JavaScript/Cypress code coverage (Istanbul/nyc).
- Changing production business logic to improve testability.
- Replacing existing unit tests that use mocks where mocks are appropriate.

---

## 3. Coverage Tooling Setup

### Configuration (`pyproject.toml`)

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

### CI integration (`scripts/run_ephemeral_python_tests.sh`)

Wrap `bench run-tests` invocation with `coverage run` and emit `coverage report` + `coverage xml` (for artifact upload):

```bash
coverage run $(which bench) --site "$SITE_NAME" run-tests --app asn_module
coverage report
coverage xml -o coverage.xml
```

If `coverage run $(which bench)` fails to capture subprocess coverage (Frappe spawns workers), fall back to `COVERAGE_PROCESS_START` with a `.coveragerc` sitecustomize approach — this must be resolved in the first implementation task before proceeding.

### CI artifact

Upload `coverage.xml` alongside existing test artifacts in `.github/workflows/ci.yml`.

---

## 4. Baseline Measurement

Before writing any new tests, run `coverage report` with the configuration from Section 3 to establish the actual baseline percentage. This grounds the 95% target in reality and identifies which modules contribute the most uncovered lines.

If baseline reveals that existing test files for `qr_engine/dispatch.py` (8 tests in `test_dispatch.py`) or `qr_engine/token.py` (10 tests in `test_token.py`) leave significant gaps in those modules, expand scope to add incremental tests for those files as well.

---

## 5. Unit Tests for Untested Core Modules

### 5a. `qr_engine/scan_codes.py` (12-15 tests)

**New file:** `asn_module/qr_engine/tests/test_scan_codes.py`

Pure function tests (no DB):
- `format_scan_code_for_display`: empty, short, exact group, odd length
- `normalize_scan_code`: None, dashes, spaces, lowercase

FrappeTestCase tests (real DB):
- `get_or_create_scan_code`: creates new, returns existing active, rejects empty args
- `get_scan_code_doc`: found, not found, normalized lookup
- `validate_scan_code_row`: Active OK, Used blocked, Used+rescan-safe OK, Revoked blocked, Expired blocked, expiry date check
- `record_successful_scan`: increments count, sets Used for non-rescan-safe, stays Active for rescan-safe
- `verify_registry_row_points_to_existing_source`: valid source, missing source, missing doctype

### 5b. `traceability.py` (6-8 tests)

**New file:** `asn_module/tests/test_traceability.py`

Pure function tests:
- `_idempotency_key`: deterministic, varies with each input field

FrappeTestCase tests:
- `emit_asn_item_transition`: creates row, deduplicates on replay, returns None on empty ASN, different ref_name same state creates new row
- `get_latest_transition_rows_for_asn`: returns latest per item, empty ASN returns empty, respects limit

### 5c. `asn_item_transition_trace.py` report (4-6 incremental tests)

**Existing file to extend:** `asn_module/tests/test_transition_trace_report.py`

This file already contains `test_execute_returns_columns_and_rows_without_filters` and `test_execute_respects_limit`. Add **incremental** tests only for uncovered paths:
- Filter by item_code, state, date range, ref_doctype (combined filter test)
- `failures_only` filter
- `search` text filter
- Limit clamping (>500 clamped to 500, <1 clamped to 1)

### 5d. `commands.py` (5-6 tests)

**New file:** `asn_module/tests/test_commands.py`

FrappeTestCase tests for `verify_scan_code_registry`:
- All valid returns `ok: True`
- Orphan scan code returns `ok: False` with orphan listed
- Permission check (unpermitted user raises PermissionError)

FrappeTestCase tests for `verify_qr_action_registry`:
- All canonical actions present returns `ok: True`
- Missing action detected returns `ok: False` with missing list populated
- Mismatched `handler_method` detected returns `ok: False` with mismatched list populated

### 5e. `handlers/utils.py` (3 tests)

**New file:** `asn_module/handlers/tests/test_utils.py`

FrappeTestCase tests:
- `attach_qr_to_doc`: creates File doc attached to target, correct filename pattern
- Invalid base64 raises error
- Missing `image_base64` key in `qr_result` raises KeyError

### 5f. `setup_actions.py` (2-3 tests)

**New file:** `asn_module/tests/test_setup_actions.py`

FrappeTestCase tests:
- `register_actions`: after call, QR Action Registry contains all 7 expected action keys
- Idempotent: calling twice does not duplicate rows
- Each action maps to a valid handler dotted path (importable)

### 5g. `templates/pages/asn.py` (0-3 incremental tests)

**Existing file:** `asn_module/templates/pages/test_asn.py` (17 tests exist after PR #5)

The portal list/detail page now has thorough test coverage including cancel and delete portal endpoints. Review baseline coverage; add incremental tests only if uncovered branches remain in `get_context`, `has_website_permission`, or `_ensure_asn_route`.

### 5h. `templates/pages/asn_new_services.py` (15-20 tests)

**New file:** `asn_module/templates/pages/test_asn_new_services.py`

This is the **largest untested module** (404 lines, 20+ public functions, zero dedicated test file). Currently only exercised indirectly through `test_asn_new.py`.

Pure function tests (no DB):
- `parse_positive_qty`: positive, zero, negative, empty, non-numeric
- `parse_non_negative_rate`: zero OK, negative raises, empty raises
- `parse_optional_non_negative_rate`: None/empty returns None, negative raises, valid returns float
- `parse_required_supplier_invoice_amount`: valid, zero, negative, empty
- `normalize_group_value`: whitespace, None, normal
- `normalize_group_field`: field mapping correctness

FrappeTestCase tests (real DB):
- `get_supplier_open_purchase_orders`: returns only open POs for logged-in supplier
- `validate_selected_purchase_orders`: empty list raises, invalid PO raises, valid POs pass
- `fetch_purchase_order_items`: returns items with correct fields, respects PO filter
- `validate_qty_within_remaining`: within limit OK, exactly at limit OK, over limit raises
- `enforce_bulk_limits`: within limit OK, over limit raises
- `validate_bulk_group_count`: within limit OK, exceeds raises
- `validate_invoice_group_consistency`: matching group OK, field mismatch raises

### 5i. `templates/pages/asn_new.py` (8-12 incremental tests)

**Existing file to extend:** `asn_module/templates/pages/test_asn_new.py` (13 tests exist)

Existing tests cover parser edge cases and error paths well. Add incremental tests for untested happy paths and branches:
- `get_context` success path for `mode == "single"` (POST with valid data)
- `get_context` success path for `mode == "bulk"` (POST with valid CSV)
- `get_context` when request method is GET (early return, renders form)
- `_create_single_asn` happy path through `_insert_and_submit_asn`
- `_create_bulk_asns` happy path (at least one valid group)
- `_parse_single_rows` with missing required fields (error accumulation)
- `_request_supplier_invoice_amount`: valid, zero, negative, empty
- `_default_asn_route`: returns expected URL format

### 5j. `templates/pages/asn_new_search.py` (2-3 incremental tests)

**Existing file to extend:** `asn_module/templates/pages/test_asn_new_search.py` (3 tests exist)

Add incremental tests for uncovered branches:
- `_get_supplier` when supplier is None (raises permission error)
- `search_open_purchase_orders` with empty `txt` (returns all matching POs)
- `search_purchase_order_items` with `txt` filter matching item names

### 5k. `supplier_asn_portal.py` — no new tests needed

This module (43 lines) already has adequate coverage from `asn_module/tests/test_supplier_asn_portal.py` (4 tests). Only trivial branches (empty string input) are uncovered. No spec section needed.

---

## 6. Complete Realistic Integration Tests

Per existing plan `docs/superpowers/plans/2026-04-04-realistic-integration-tests.md` (Tasks 2-3, currently unstarted):

### Task 2: Real attachment context

- Implement `real_asn_qr_barcode_context()` in `asn_module/asn_module/doctype/asn/test_asn.py` (or integration fixtures).
- Uses real `save_file` via Frappe API with minimal valid PNG bytes.
- If barcode libs fail in CI, narrow patch to only `generate_barcode` with docstring exception note.

### Task 3: Remove `get_roles` patch from `test_e2e_flow`

- Use `ensure_integration_user` + `integration_user_context` from `asn_module/tests/integration/fixtures.py`.
- Remove `patch("asn_module.qr_engine.dispatch.frappe.get_roles", ...)` from golden-path tests.
- Keep `get_roles` patches only for explicit negative-path role tests (documented exceptions).

---

## 7. Cypress API-Backed E2E (per `2026-04-04-cypress-api-backed-e2e-design.md`)

### Suite layout

- Move existing smoke specs to `cypress/integration/smoke/`
- New nightly specs in `cypress/integration/nightly/`

### Config changes

- `cypress.config.cjs`: `specPattern` driven by `E2E_SUITE` env var (`smoke` | `nightly` | `all`)
- `scripts/run_ephemeral_e2e.sh`: pass `E2E_SUITE` based on mode (`smoke` -> `smoke`, `ci` -> `nightly`)

### Nightly specs

**`cypress/integration/nightly/asn_desk_nightly.js`:**
- Seed minimal ASN via `cy.call` (whitelisted Frappe method or test helper)
- Visit ASN list, assert seeded ASN visible
- Visit ASN detail, assert key fields rendered

**`cypress/integration/nightly/scan_station_nightly.js`:**
- Build dispatchable context via single `cy.call` to server-side test helper
- Helper returns scan code + doc names
- Visit Scan Station, enter scan code in input
- Assert success UI or expected error path

### Server-side test helper

If building dispatchable context exceeds ~3-4 `cy.call` hops, add one whitelisted test helper (gated behind `allow_tests`) that creates submitted ASN + PR + scan code and returns the scan code string.

---

## 8. Sequencing

1. **Coverage tooling** (Section 3) — configure and verify invocation works
2. **Baseline measurement** (Section 4) — run coverage, identify actual gaps, validate 95% is reachable
3. **Unit tests** (Section 5) — biggest coverage lift (~65-75 new tests across 11 modules)
4. **Integration test gaps** (Section 6) — complete `2026-04-04-realistic-integration-tests-design.md` Tasks 2-3
5. **Cypress E2E** (Section 7) — complete `2026-04-04-cypress-api-backed-e2e-design.md`, does not affect Python coverage

---

## 9. Acceptance Criteria

- `coverage report --fail-under=95` passes after Sections 3-6
- All `bench run-tests --app asn_module` pass
- Cypress nightly specs pass on both Frappe 15/16 matrix rows (Section 7)
- No new `get_roles` patches on golden-path tests
- Coverage XML uploaded as CI artifact
- Baseline measurement documented before new tests are written

---

## 10. Risks and Mitigations

- **Risk:** `coverage run $(which bench)` doesn't capture subprocess coverage
  **Mitigation:** Resolve in first implementation task; fall back to `COVERAGE_PROCESS_START` with sitecustomize if needed
- **Risk:** Baseline reveals 95% is unreachable with proposed modules alone
  **Mitigation:** Baseline step (Section 4) identifies all gaps early; expand scope to additional modules if needed before writing tests
- **Risk:** Existing tests for `dispatch.py` / `token.py` have significant uncovered branches
  **Mitigation:** Baseline measurement flags these; add incremental tests if needed (not pre-scoped since existing test files have 8 and 10 tests respectively)
- **Risk:** Barcode libs unavailable in CI
  **Mitigation:** Narrow patch to `generate_barcode` only; document as exception
- **Risk:** Cypress nightly flakiness
  **Mitigation:** API-seed approach reduces UI interaction surface; condition-based waits; artifacts on failure
- **Risk:** Portal code (~1,000 new lines in `asn_new.py` + `asn_new_services.py`) dominates the coverage denominator
  **Mitigation:** Sections 5h-5i add 23-32 dedicated tests; `asn_new_services.py` has the highest line count and is prioritized first in implementation
- **Risk:** Install-time code (`setup.py`, `setup_actions.py`) runs before coverage starts
  **Mitigation:** `setup_actions.py` is tested directly via unit tests (Section 5f); `setup.py` (10 lines, `after_install` entry point) is omitted from coverage scope since it only runs at install time
