# Coverage Gap Closure — Design Specification

**Status:** Approved (brainstorming session, 2026-04-05)
**Target:** Python line coverage >= 95% via `coverage.py`
**Approach:** Coverage tooling first, then unit tests for gaps, then integration test completion, then Cypress E2E

---

## 1. Goals

- Configure `coverage.py` to measure Python line coverage for `asn_module` in CI and locally.
- Add direct unit tests for 5 untested core modules (~30 new test methods).
- Complete remaining realistic integration test tasks (Spec 5 Tasks 2-3).
- Implement Cypress API-backed nightly E2E specs (Spec 4).

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

Wrap `bench run-tests` invocation with `coverage run` and emit `coverage report` + `coverage xml` (for artifact upload). The exact invocation pattern depends on Frappe's test runner:

- Primary: `coverage run $(which bench) --site "$SITE_NAME" run-tests --app asn_module`
- Fallback: `coverage run -m frappe.test_runner --app asn_module` if bench wrapper interferes

Verify which pattern works during implementation; pick one and document.

### CI artifact

Upload `coverage.xml` alongside existing test artifacts in `.github/workflows/ci.yml`.

---

## 4. Unit Tests for Untested Core Modules

### 4a. `qr_engine/scan_codes.py` (12-15 tests)

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

### 4b. `traceability.py` (6-8 tests)

**New file:** `asn_module/tests/test_traceability.py`

Pure function tests:
- `_idempotency_key`: deterministic, varies with each input field

FrappeTestCase tests:
- `emit_asn_item_transition`: creates row, deduplicates on replay, returns None on empty ASN, different ref_name same state creates new row
- `get_latest_transition_rows_for_asn`: returns latest per item, empty ASN returns empty, respects limit

### 4c. `asn_item_transition_trace.py` report (6-8 tests)

**Existing file to extend:** `asn_module/tests/test_transition_trace_report.py`

FrappeTestCase tests:
- `execute` with no filters returns columns + rows
- Filter by ASN, item_code, state, date range, ref_doctype
- `failures_only` filter
- `search` text filter
- Pagination (`limit_page_length`, `limit_start`)
- Limit clamping (>500 clamped to 500, <1 clamped to 1)

### 4d. `commands.py` (2-3 tests)

**New file:** `asn_module/tests/test_commands.py`

FrappeTestCase tests:
- `verify_scan_code_registry`: all valid returns `ok: True`
- Orphan scan code returns `ok: False` with orphan listed
- Permission check (unpermitted user raises PermissionError)

### 4e. `handlers/utils.py` (2 tests)

**New file:** `asn_module/handlers/tests/test_utils.py`

FrappeTestCase tests:
- `attach_qr_to_doc`: creates File doc attached to target, correct filename pattern
- Invalid base64 raises error

---

## 5. Complete Realistic Integration Tests (Spec 5 Tasks 2-3)

Per existing plan `docs/superpowers/plans/2026-04-04-realistic-integration-tests.md`:

### Task 2: Real attachment context

- Implement `real_asn_qr_barcode_context()` in `asn_module/asn_module/doctype/asn/test_asn.py` (or integration fixtures).
- Uses real `save_file` via Frappe API with minimal valid PNG bytes.
- If barcode libs fail in CI, narrow patch to only `generate_barcode` with docstring exception note.

### Task 3: Remove `get_roles` patch from `test_e2e_flow`

- Use `ensure_integration_user` + `integration_user_context` from `asn_module/tests/integration/fixtures.py`.
- Remove `patch("asn_module.qr_engine.dispatch.frappe.get_roles", ...)` from golden-path tests.
- Keep `get_roles` patches only for explicit negative-path role tests (documented exceptions).

---

## 6. Cypress API-Backed E2E (Spec 4)

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

## 7. Sequencing

1. **Coverage tooling** (Section 3) — measure baseline
2. **Unit tests** (Section 4) — biggest coverage lift
3. **Integration test gaps** (Section 5) — complete Spec 5
4. **Cypress E2E** (Section 6) — complete Spec 4, does not affect Python coverage

---

## 8. Acceptance Criteria

- `coverage report --fail-under=95` passes after Sections 3-5
- All `bench run-tests --app asn_module` pass
- Cypress nightly specs pass on both Frappe 15/16 matrix rows (Section 6)
- No new `get_roles` patches on golden-path tests
- Coverage XML uploaded as CI artifact

---

## 9. Risks and Mitigations

- **Risk:** `coverage run $(which bench)` doesn't capture subprocess coverage
  **Mitigation:** Test locally first; fall back to `coverage run -m frappe.test_runner` or `COVERAGE_PROCESS_START` for subprocess tracing
- **Risk:** Barcode libs unavailable in CI
  **Mitigation:** Narrow patch to `generate_barcode` only; document as exception
- **Risk:** Cypress nightly flakiness
  **Mitigation:** API-seed approach reduces UI interaction surface; condition-based waits; artifacts on failure
