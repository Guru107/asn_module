# Property-Based Testing (Phased Rollout) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable, CI-gated property-based tests for ASN logic in two phases: fast pure-function properties first, then bounded DB-integrated properties.

**Architecture:** Introduce a dedicated property-test package and dedicated CI stage to isolate runtime and flake risk from existing server tests. Phase 1 targets deterministic parser/normalizer/token invariants; Phase 2 adds bounded DB-backed ASN flow invariants once Phase 1 is stable.

**Tech Stack:** Frappe test runner (`bench run-tests`), Python `unittest` + Hypothesis, GitHub Actions.

---

## Rollout Options and Trade-offs (Decision Locked)

1. Dedicated `Property Tests` CI job (selected)
Trade-off: Slightly longer total CI wall clock due to extra job, but failures are isolated and diagnosis is faster.
2. Fold property tests into existing `Server` job (rejected)
Trade-off: Simpler workflow file, but slower/red `Server` job becomes noisy and makes triage harder.
3. Nightly-only property tests (rejected)
Trade-off: Fast PR CI, but regressions are detected late and merge gate is weakened.

Locked decision: Option 1 with merge-blocking from day one for Phase 1 modules.

---

## File Structure (locked before implementation)

- Modify: `pyproject.toml`
- Create: `asn_module/property_tests/__init__.py`
- Create: `asn_module/property_tests/settings.py`
- Create: `asn_module/property_tests/strategies.py`
- Create: `asn_module/property_tests/test_asn_new_services_properties.py`
- Create: `asn_module/property_tests/test_scan_code_properties.py`
- Create: `asn_module/property_tests/test_token_properties.py`
- Create (phase 2): `asn_module/property_tests/test_asn_db_properties.py`
- Create: `scripts/run_ephemeral_property_tests.sh`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/ProjectOverview.md`

### Task 0: Add Reproducible Property-Test Dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add Hypothesis as bench dev dependency**

```toml
[tool.bench.dev-dependencies]
hypothesis = ">=6.140,<7"
```

- [ ] **Step 2: Reinstall dev dependencies in bench**

Run: `cd ~/Workspace/bench16 && bench setup requirements --dev`
Expected: Hypothesis gets installed in bench env.

- [ ] **Step 3: Confirm dependency is importable**

Run: `cd ~/Workspace/bench16 && ./env/bin/python -c "import hypothesis; print(hypothesis.__version__)"`
Expected: prints version, exits 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build(test): add hypothesis dev dependency"
```

### Task 1: Scaffold Property Test Harness

**Files:**
- Create: `asn_module/property_tests/__init__.py`
- Create: `asn_module/property_tests/settings.py`
- Create: `asn_module/property_tests/strategies.py`
- Test: `asn_module/property_tests/test_asn_new_services_properties.py`

- [ ] **Step 1: Write the failing harness smoke test**

```python
# asn_module/property_tests/test_asn_new_services_properties.py
from hypothesis import given
from hypothesis import strategies as st


def _identity(x):
    return x


@given(st.text())
def test_property_harness_smoke_identity(text_value):
    assert _identity(text_value) == text_value
```

- [ ] **Step 2: Run test to verify initial failure before support files exist**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_asn_new_services_properties --lightmode`
Expected: may fail because `settings.py`/support files are not yet created.

- [ ] **Step 3: Add Hypothesis settings/profile helper**

```python
# asn_module/property_tests/settings.py
import os
from hypothesis import HealthCheck, settings

PROFILE = os.getenv("HYPOTHESIS_PROFILE", "ci")

settings.register_profile(
    "ci",
    max_examples=80,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.register_profile(
    "local",
    max_examples=300,
    deadline=None,
)
settings.load_profile(PROFILE)
```

- [ ] **Step 4: Add reusable domain strategies**

```python
# asn_module/property_tests/strategies.py
from hypothesis import strategies as st

numeric_strings = st.from_regex(r"-?\d+(\.\d+)?", fullmatch=True)
scan_text = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -", min_size=0, max_size=64)
invoice_strings = st.from_regex(r"[A-Z0-9\-]{1,40}", fullmatch=True)
```

- [ ] **Step 5: Run the harness test and confirm pass**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_asn_new_services_properties --lightmode`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add asn_module/property_tests/__init__.py asn_module/property_tests/settings.py asn_module/property_tests/strategies.py asn_module/property_tests/test_asn_new_services_properties.py
git commit -m "test(property): scaffold hypothesis harness and shared strategies"
```

### Task 2: Phase 1 Properties for ASN Parser/Normalizer Logic

**Files:**
- Modify: `asn_module/property_tests/test_asn_new_services_properties.py`
- Test target: `asn_module/templates/pages/asn_new_services.py`

- [ ] **Step 1: Write failing properties for parsing boundaries**

```python
from hypothesis import given, assume
from hypothesis import strategies as st

from asn_module.templates.pages.asn_new_services import (
    PortalValidationError,
    normalize_group_field,
    normalize_group_value,
    parse_non_negative_rate,
    parse_optional_non_negative_rate,
    parse_positive_qty,
)


@given(st.floats(min_value=0.0001, allow_infinity=False, allow_nan=False))
def test_parse_positive_qty_accepts_positive(x):
    assert parse_positive_qty(str(x), row_number=1, field="qty") > 0


@given(st.floats(max_value=0, allow_infinity=False, allow_nan=False))
def test_parse_positive_qty_rejects_non_positive(x):
    try:
        parse_positive_qty(str(x), row_number=1, field="qty")
        assert False
    except PortalValidationError:
        assert True
```

- [ ] **Step 2: Add idempotence/normalization properties**

```python
@given(st.text())
def test_normalize_group_value_idempotent(text_value):
    first = normalize_group_value(text_value)
    second = normalize_group_value(first)
    assert first == second


@given(st.decimals(allow_nan=False, allow_infinity=False))
def test_supplier_invoice_amount_normalization_numeric_equivalence(value):
    raw = str(value)
    normalized = normalize_group_field("supplier_invoice_amount", raw)
    if raw.strip():
        assert normalized == str(float(raw))
```

- [ ] **Step 3: Run property module tests**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_asn_new_services_properties --lightmode`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add asn_module/property_tests/test_asn_new_services_properties.py
git commit -m "test(property): add parser and normalization invariants for asn_new_services"
```

### Task 3: Phase 1 Properties for Scan Code Canonicalization

**Files:**
- Create: `asn_module/property_tests/test_scan_code_properties.py`
- Test target: `asn_module/qr_engine/scan_codes.py`

- [ ] **Step 1: Write failing normalization properties**

```python
from hypothesis import given

from asn_module.property_tests.strategies import scan_text
from asn_module.qr_engine.scan_codes import format_scan_code_for_display, normalize_scan_code


@given(scan_text)
def test_normalize_scan_code_idempotent(raw):
    once = normalize_scan_code(raw)
    twice = normalize_scan_code(once)
    assert once == twice


@given(scan_text)
def test_format_preserves_normalized_code(raw):
    normalized = normalize_scan_code(raw)
    display = format_scan_code_for_display(normalized)
    assert display.replace("-", "") == normalized
```

- [ ] **Step 2: Run scan-code property tests**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_scan_code_properties --lightmode`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add asn_module/property_tests/test_scan_code_properties.py
git commit -m "test(property): add scan code normalization and formatting invariants"
```

### Task 4: Phase 1 Properties for Token Round-Trip and Tamper Rejection

**Files:**
- Create: `asn_module/property_tests/test_token_properties.py`
- Test target: `asn_module/qr_engine/token.py`

- [ ] **Step 1: Write failing create/verify round-trip property**

```python
from hypothesis import given
from hypothesis import strategies as st

from asn_module.qr_engine.token import InvalidTokenError, create_token, verify_token


@given(
    action=st.from_regex(r"[a-z_]{3,40}", fullmatch=True),
    source_doctype=st.from_regex(r"[A-Za-z ]{3,40}", fullmatch=True),
    source_name=st.from_regex(r"[A-Za-z0-9\-]{1,40}", fullmatch=True),
)
def test_token_round_trip(action, source_doctype, source_name):
    token = create_token(action, source_doctype, source_name)
    payload = verify_token(token)
    assert payload["action"] == action
    assert payload["source_doctype"] == source_doctype
    assert payload["source_name"] == source_name
```

- [ ] **Step 2: Add tamper property**

```python
@given(st.text(min_size=1, max_size=8))
def test_tampered_token_rejected(suffix):
    token = create_token("create_purchase_receipt", "ASN", "ASN-001")
    tampered = token + suffix
    try:
        verify_token(tampered)
        assert False
    except InvalidTokenError:
        assert True
```

- [ ] **Step 3: Run token property tests**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_token_properties --lightmode`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add asn_module/property_tests/test_token_properties.py
git commit -m "test(property): add token round-trip and tamper invariants"
```

### Task 5: Dedicated CI Stage for Property Tests (Required PR Gate)

**Files:**
- Create: `scripts/run_ephemeral_property_tests.sh`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write failing CI stage (job exists but script missing)**

Add `Property Tests` job in CI referencing new script.

- [ ] **Step 2: Create script for isolated property run**

```bash
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../bench16" && pwd)}"

CI=true "$APP_ROOT/scripts/run_ephemeral_python_tests.sh" asn_module.property_tests
```

- [ ] **Step 3: Wire CI job**

- Add a parallel job named `Property Tests`.
- Reuse service containers and setup/install flow from `Server`.
- Run `scripts/run_ephemeral_property_tests.sh`.
- Keep this check required in branch protection (merge-blocking).

- [ ] **Step 4: Run local dry validation for syntax only**

Run: `bash -n scripts/run_ephemeral_property_tests.sh`
Expected: no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_ephemeral_property_tests.sh .github/workflows/ci.yml
git commit -m "ci: add dedicated property-test stage for PR gating"
```

### Task 6: Documentation and Developer Workflow

**Files:**
- Modify: `docs/ProjectOverview.md`

- [ ] **Step 1: Add run commands**

Document:
- local phase-1 run command,
- local full property run command,
- CI profile env usage (`HYPOTHESIS_PROFILE`).

- [ ] **Step 2: Add triage guidance**

Document workflow for shrinking/counterexample handling and regression promotion.

- [ ] **Step 3: Commit**

```bash
git add docs/ProjectOverview.md
git commit -m "docs: add property-testing commands and failure triage guide"
```

### Task 7 (Phase 2): DB-Integrated Property Invariants

**Files:**
- Create: `asn_module/property_tests/test_asn_db_properties.py`

- [ ] **Step 1: Add bounded DB generators and invariants**

Properties to implement:
- valid generated bulk groups => created ASN count equals unique invoice count,
- mixed PO in one invoice group => always rejected,
- generated qty exceeding remaining PO qty => always rejected,
- generated single ASN with >1 selected PO => always rejected.

- [ ] **Step 2: Run DB property module in isolation**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests.test_asn_db_properties --lightmode`
Expected: PASS with bounded runtime.

- [ ] **Step 3: Add DB property module to property CI script**

Extend `scripts/run_ephemeral_property_tests.sh` module list to include DB property module.

- [ ] **Step 4: Commit**

```bash
git add asn_module/property_tests/test_asn_db_properties.py scripts/run_ephemeral_property_tests.sh
git commit -m "test(property): add bounded DB invariants for ASN creation flows"
```

### Task 8: Final Verification Before PR

**Files:**
- Test only

- [ ] **Step 1: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: PASS.

- [ ] **Step 2: Run property suite**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.property_tests --lightmode`
Expected: PASS.

- [ ] **Step 3: Run baseline safety module**

Run: `cd ~/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_services --lightmode`
Expected: PASS.

- [ ] **Step 4: Commit verification artifacts if needed (none expected)**

No code changes expected in this step.

## Acceptance Criteria

- Phase 1 property modules exist and pass in CI as a required check.
- Server CI runtime regression is limited because property tests run in dedicated stage.
- Property failures produce actionable minimized counterexamples.
- Phase 2 DB property module is merged only after phase-1 stage has remained stable across a one-week window with no flake reruns.

## Phase Transition Rule (locked)

Start Phase 2 only when all are true:
- `Property Tests` CI job is green for 7 consecutive days,
- no flaky rerun labels on property stage during that window,
- median property job duration remains within acceptable CI budget for this repo.
