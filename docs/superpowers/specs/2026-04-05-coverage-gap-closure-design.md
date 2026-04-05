# Coverage Gap Closure — Design Specification

**Status:** Approved (brainstorming session, 2026-04-05)
**Target:** Python line coverage >= 95% via `coverage.py`
**Approach:** Coverage tooling first, then unit tests for gaps, then integration test completion, then Cypress E2E

---

## 1. Goals

- Configure `coverage.py` to measure Python line coverage for `asn_module` in CI and locally.
- **Measure baseline** before writing new tests to validate the 95% target is reachable.
- Add direct unit tests for 7 untested core modules (~38 new test methods).
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

### 5d. `commands.py` (2-3 tests)

**New file:** `asn_module/tests/test_commands.py`

FrappeTestCase tests:
- `verify_scan_code_registry`: all valid returns `ok: True`
- Orphan scan code returns `ok: False` with orphan listed
- Permission check (unpermitted user raises PermissionError)

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

### 5g. `templates/pages/asn.py` (3-4 incremental tests)

**Existing file:** `asn_module/templates/pages/test_asn.py` (7 tests exist)

Review existing coverage. If `get_context`, `has_website_permission`, or `_ensure_asn_route` have uncovered branches, add incremental tests:
- `has_website_permission`: supplier sees own ASN, blocked from other supplier's ASN
- `_ensure_asn_route`: route generation for valid/invalid ASN
- `get_context`: context populated with expected keys

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
3. **Unit tests** (Section 5) — biggest coverage lift (~38 new tests across 7 modules)
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
- **Risk:** Install-time code (`setup.py`, `setup_actions.py`) runs before coverage starts
  **Mitigation:** `setup_actions.py` is tested directly via unit tests (Section 5f); `setup.py` (10 lines, `after_install` entry point) is omitted from coverage scope since it only runs at install time
