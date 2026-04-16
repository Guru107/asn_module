# Sales Invoice 1D Barcode (16-Char Only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a strict 16-character Code128 scan-code contract for ASN invoice barcode flow, with no 12-character legacy compatibility.

**Architecture:** Keep `Scan Code` as the server-side source of truth and enforce code shape at normalization/lookup boundaries to reject invalid payloads early. Preserve existing dispatch lifecycle/state checks and generation flow, while tightening UI guidance and tests to 16-char-only behavior.

**Tech Stack:** Frappe v16, Python `unittest`/`FrappeTestCase`, Cypress nightly E2E, existing `qr_engine` barcode pipeline.

---

## Decision and Trade-offs (Locked)

1. Strict 16-char-only validation at server boundary (selected)
Trade-off: Simpler, deterministic behavior and no migration logic; any non-16 code is rejected immediately.
2. Dual 12/16 compatibility during transition (rejected)
Trade-off: Lower rollout risk but adds branching complexity and is unnecessary because there are no legacy users.
3. UI-only validation with permissive server lookup (rejected)
Trade-off: Less backend churn but weaker guarantees and inconsistent behavior across clients.

Locked decision: Option 1.

Robust validation rules (mandatory):
- Normalize input by trimming and removing whitespace only (no permissive separator rewriting).
- Accept only exact `SCAN_CODE_LENGTH == 16`.
- Accept only characters from `SCAN_CODE_ALPHABET`.
- Reject all non-canonical shapes (dashed strings, legacy token URLs, wrong length, invalid charset) with the standard "Unknown or invalid scan code" flow.

---

## File Structure (locked before implementation)

- Modify: `asn_module/qr_engine/scan_codes.py`
- Modify: `asn_module/qr_engine/tests/test_scan_codes.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch_errors.py`
- Modify: `asn_module/asn_module/page/scan_station/scan_station.js`
- Modify (if needed): `cypress/integration/nightly/scan_station_nightly.js`

### Task 1: Enforce 16-Char Canonical Contract in Scan-Code Core

**Files:**
- Modify: `asn_module/qr_engine/scan_codes.py`
- Test: `asn_module/qr_engine/tests/test_scan_codes.py`

- [ ] **Step 1: Write failing unit tests for 16-char-only canonical rules**

```python
def test_normalize_scan_code_rejects_wrong_length(self):
    self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQ"), "")
    self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQRST"), "")

def test_normalize_scan_code_rejects_invalid_characters(self):
    self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQ0"), "")
    self.assertEqual(normalize_scan_code("ABCDEFGHJKLMNPQI"), "")

def test_normalize_scan_code_rejects_dashes(self):
    self.assertEqual(normalize_scan_code("ABCD-EFGH-JKLM-NPQR"), "")
```

- [ ] **Step 2: Run the targeted tests and confirm failure**

Run: `cd ~/Workspace/bench16 && bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_scan_codes --lightmode`  
Expected: FAIL on new canonical tests.

- [ ] **Step 3: Implement minimal 16-char validation in `normalize_scan_code`**

```python
SCAN_CODE_LENGTH = 16

def normalize_scan_code(code: str | None) -> str:
    raw = (code or "").strip().replace(" ", "").upper()
    if len(raw) != SCAN_CODE_LENGTH:
        return ""
    if any(ch not in SCAN_CODE_ALPHABET for ch in raw):
        return ""
    return raw
```

- [ ] **Step 4: Run scan-code tests and confirm pass**

Run: `cd ~/Workspace/bench16 && bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_scan_codes --lightmode`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/qr_engine/scan_codes.py asn_module/qr_engine/tests/test_scan_codes.py
git commit -m "feat(scan-code): enforce 16-char canonical scan code format"
```

### Task 2: Keep Dispatch Behavior Explicit for Invalid Shapes

**Files:**
- Modify: `asn_module/qr_engine/tests/test_dispatch_errors.py`
- Modify (if needed): `asn_module/qr_engine/tests/test_dispatch.py`

- [ ] **Step 1: Add failing dispatch tests for malformed/invalid-length input**

```python
def test_dispatch_invalid_length_scan_code_raises(self):
    with integration_user_context():
        with self.assertRaises(ScanCodeNotFoundError):
            dispatch(code="TOO-SHORT", device_info="test")

def test_dispatch_invalid_charset_scan_code_raises(self):
    with integration_user_context():
        with self.assertRaises(ScanCodeNotFoundError):
            dispatch(code="ABCDEFGHJKLMNPQ0", device_info="test")

def test_dispatch_dashed_scan_code_raises(self):
    with integration_user_context():
        with self.assertRaises(ScanCodeNotFoundError):
            dispatch(code="ABCD-EFGH-JKLM-NPQR", device_info="test")
```

- [ ] **Step 2: Run dispatch error tests and confirm behavior**

Run: `cd ~/Workspace/bench16 && bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch_errors --lightmode`  
Expected: PASS with `"Unknown or invalid scan code"` path.

- [ ] **Step 3: Commit**

```bash
git add asn_module/qr_engine/tests/test_dispatch_errors.py asn_module/qr_engine/tests/test_dispatch.py
git commit -m "test(dispatch): cover malformed and non-canonical scan code inputs"
```

### Task 3: Align Scan Station UX with 16-Char Contract

**Files:**
- Modify: `asn_module/asn_module/page/scan_station/scan_station.js`
- Modify (if needed): `cypress/integration/nightly/scan_station_nightly.js`

- [ ] **Step 1: Add/adjust failing E2E assertions for 16-char scan flow messaging**

```javascript
cy.get(".scan-input").type("TOO-SHORT{enter}");
cy.get(".scan-error").should("be.visible");
```

- [ ] **Step 2: Update client-side hint/auto-submit threshold and comments**

```javascript
// 16-char scan codes or full dispatch URLs
if (val && (val.length >= 16 || /^https?:\/\//i.test(val))) {
    process_scan(val);
}
```

- [ ] **Step 3: Run impacted E2E spec locally**

Run: `cd ~/Workspace/asn_module && npx cypress run --spec cypress/integration/nightly/scan_station_nightly.js`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add asn_module/asn_module/page/scan_station/scan_station.js cypress/integration/nightly/scan_station_nightly.js
git commit -m "feat(scan-station): align scanner UX and thresholds for 16-char codes"
```

### Task 4: End-to-End Verification and Quality Gates

**Files:**
- No new files; verification-only task.

- [ ] **Step 1: Run Python targeted suite**

Run:
```bash
cd ~/Workspace/bench16
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_scan_codes --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch_errors --lightmode
```
Expected: all PASS.

- [ ] **Step 2: Run formatting/lint checks**

Run: `cd ~/Workspace/asn_module && pre-commit run --all-files`  
Expected: PASS.

- [ ] **Step 3: Commit any test-only fixes from verification**

```bash
git add -A
git commit -m "test: stabilize 16-char barcode contract verification"
```

### Task 5: CI Signal Validation (Ephemeral + PR Checks)

**Files:**
- No new files; workflow validation.

- [ ] **Step 1: Run ephemeral server tests locally**

Run: `cd ~/Workspace/asn_module && scripts/run_ephemeral_python_tests.sh`  
Expected: PASS with no scan-code contract regressions.

- [ ] **Step 2: Push branch and validate GitHub checks**

Run:
```bash
git push
gh pr checks --watch
```
Expected: Server + E2E green; no scan-code-related failures.

- [ ] **Step 3: If failures appear, fix only 16-char-contract regressions and re-run impacted checks**

Run impacted module/spec commands first, then `pre-commit run --all-files`.
