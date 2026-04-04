# Realistic integration tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add integration tests that minimize mocks (real users/roles, real file pipeline where feasible, `dispatch(code=…)` against production registry handlers), assert **ASN Transition Log** and **report/summary** consistency, and cover `**verify_scan_code_registry`**.

**Architecture:** New package `asn_module/tests/integration/` holds shared fixtures (users, optional real attachment helper). Existing `test_e2e_flow.py` and handler tests are **refined** rather than deleted: golden paths drop `get_roles` patches and reduce attachment/QR mocks where practical. New focused modules add trace + registry-command coverage. Unit tests under `qr_engine/tests` and dispatch fake-handler tests **remain**.

**Tech Stack:** `FrappeTestCase`, `bench run-tests --app asn_module`, ERPNext test records from `asn_module.utils.test_setup.before_tests` / `test_asn` helpers.

**Spec:** `docs/superpowers/specs/2026-04-04-realistic-integration-tests-design.md`

---

## Production registry actions (from `asn_module/setup_actions.py`)


| `action_key`                     | `handler_method`                                                               | `source_doctype`     | Roles (allowed_roles)           |
| -------------------------------- | ------------------------------------------------------------------------------ | -------------------- | ------------------------------- |
| `create_purchase_receipt`        | `asn_module.handlers.purchase_receipt.create_from_asn`                         | ASN                  | Stock User, Stock Manager       |
| `create_stock_transfer`          | `asn_module.handlers.stock_transfer.create_from_quality_inspection`            | Quality Inspection   | Stock User, Stock Manager       |
| `create_purchase_return`         | `asn_module.handlers.purchase_return.create_from_quality_inspection`           | Quality Inspection   | Stock User, Stock Manager       |
| `create_purchase_invoice`        | `asn_module.handlers.purchase_invoice.create_from_purchase_receipt`            | Purchase Receipt     | Accounts User, Accounts Manager |
| `confirm_putaway`                | `asn_module.handlers.putaway.confirm_putaway`                                  | Purchase Receipt     | Stock User, Stock Manager       |
| `create_subcontracting_dispatch` | `asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order` | Subcontracting Order | Stock User, Stock Manager       |
| `create_subcontracting_receipt`  | `asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order`  | Subcontracting Order | Stock User, Stock Manager       |


**Integration target:** at least **one** `dispatch(code=…)` (or documented equivalent) test per row above on golden paths, except where a row is explicitly deferred to a follow-up milestone with a comment in code + spec appendix.

---

## File map


| Path                                                                | Action                                                                                                                            |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `asn_module/tests/integration/__init__.py`                          | **Create** — package marker                                                                                                       |
| `asn_module/tests/integration/fixtures.py`                          | **Create** — `ensure_integration_user`, `integration_user_context`, optional `attach_minimal_asn_files`                           |
| `asn_module/tests/integration/test_traceability_integration.py`     | **Create** — log vs summary vs report                                                                                             |
| `asn_module/tests/integration/test_registry_command_integration.py` | **Create** — `verify_scan_code_registry`                                                                                          |
| `asn_module/tests/integration/test_dispatch_actions_integration.py` | **Create** — per-`action_key` dispatch (may import helpers from `handlers/tests` / `test_asn`)                                    |
| `asn_module/tests/test_e2e_flow.py`                                 | **Modify** — remove `get_roles` patch on golden tests; use fixture user; shrink mocks per Task 3                                  |
| `asn_module/asn_module/doctype/asn/test_asn.py`                     | **Modify** — add **non-mock** helper (e.g. `real_asn_attachment_context`) alongside `_mock_asn_attachments` for gradual migration |
| `asn_module/handlers/tests/*.py`                                    | **Modify** only if shared builders must be **public** (importable) for integration package; avoid duplication                     |


---

### Task 1: Integration fixtures package

**Files:**

- Create: `asn_module/tests/integration/__init__.py`
- Create: `asn_module/tests/integration/fixtures.py`
- **Step 1:** Add `ensure_integration_user(email, roles: list[str])` that creates or updates a **User** with **User Role** children for all listed roles; use `**frappe.db.commit()`** only if required by Frappe test transaction rules (match patterns from ERPNext/Frappe test utilities in-repo).
- **Step 2:** Add context manager `integration_user_context(email)` that `**frappe.set_user(email)`** on enter and restores previous session user on exit.
- **Step 3:** Document in module docstring: **Administrator is not used** on golden paths once users exist; list which roles bundle covers `setup_actions` (Stock + Accounts).
- **Step 4:** Run `ruff check asn_module/tests/integration/`.
- **Step 5:** Commit: `test: add integration test fixtures package`.

---

### Task 2: Real attachment / QR path (reduce `_mock_asn_attachments`)

**Files:**

- Modify: `asn_module/asn_module/doctype/asn/test_asn.py`
- Modify: `asn_module/tests/integration/fixtures.py` (optional re-export)
- **Step 1:** Implement `real_asn_qr_barcode_context()` (name flexible) that **does not** patch `save_file`: call real `**generate_qr` / `generate_barcode`** from the same modules ASN uses, or write **minimal valid PNG bytes** to a **temp file** and attach via `**frappe.get_doc().save_file`** / `save_file` **without** patch. If barcode libs fail in CI, document **single** narrow patch point (e.g. only `generate_barcode`) as exception in test docstring.
- **Step 2:** Add one `**TestASN`** test that **submits** ASN using the new context (duplicate smallest existing submit test) to prove it works.
- **Step 3:** Run `bench --site <site> run-tests --app asn_module --module asn_module.asn_module.doctype.asn.test_asn` (or full app module path as per bench).
- **Step 4:** Commit: `test(asn): allow submit integration test without attachment save_file mock`.

---

### Task 3: Refactor `test_e2e_flow` golden path (no `get_roles` patch)

**Files:**

- Modify: `asn_module/tests/test_e2e_flow.py`
- **Step 1:** Remove `patch("asn_module.qr_engine.dispatch.frappe.get_roles", …)` from `setUp` for `**test_full_asn_to_purchase_invoice_flow_via_dispatch`** (and any other test that should follow policy **A**).
- **Step 2:** In `setUpClass` or test start, call `ensure_integration_user` with **union of roles** needed for PR + PI dispatch (Stock User **or** Stock Manager, plus Accounts User **or** Accounts Manager).
- **Step 3:** Wrap the main test body in `integration_user_context`.
- **Step 4:** Replace `_mock_asn_attachments()` with `**real_asn_qr_barcode_context`** for ASN submit; for **PR submit**, remove patches `**generate_qr`** / `**_attach_qr_to_doc**` if real pipeline works—if not, document minimal remaining patches in test docstring (policy **A** exception).
- **Step 5:** Run `bench run-tests --app asn_module --module asn_module.tests.test_e2e_flow`.
- **Step 6:** Commit: `test(e2e): run dispatch flow under real user; reduce attachment mocks`.

---

### Task 4: Traceability integration

**Files:**

- Create: `asn_module/tests/integration/test_traceability_integration.py`
- **Step 1:** In one test, run the **same journey** as `test_full_asn_to_purchase_invoice_flow_via_dispatch` (reuse helpers; consider extracting `**build_submitted_asn_with_pr_and_pi`** shared function in `test_e2e_flow` or `fixtures` to avoid copy-paste).
- **Step 2:** After each major step (ASN submit, PR create, PR submit, PI create), query `**ASN Transition Log`** (`frappe.get_all` or `get_latest_transition_rows_for_asn`) and assert **expected states** exist (exact keys per `asn_module.traceability`).
- **Step 3:** Call `**get_item_transition_summary(asn.name)`** and assert row count and **item coverage** vs log.
- **Step 4:** Call `**execute`** from `asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace` with `filters={"asn": asn.name}` and assert row count **consistent** with summary within limit.
- **Step 5:** Run module tests; commit: `test(integration): trace log, summary, and report alignment`.

---

### Task 5: `verify_scan_code_registry` integration

**Files:**

- Create: `asn_module/tests/integration/test_registry_command_integration.py`
- **Step 1:** `**test_verify_registry_ok_after_valid_flow`:** run minimal flow creating **Scan Code** rows pointing at existing **ASN** (or DocType used in `verify_registry_row_points_to_existing_source`); `**frappe.set_user`** to user with read permission on Scan Code; `frappe.call` or direct import `**verify_scan_code_registry**`; assert `**ok**` and `orphan_count == 0`.
- **Step 2:** `**test_verify_registry_detects_orphan`:** create **Scan Code** with **invalid** `source_name` (non-existent ASN id) in `setUp`, assert `**ok` is False** and orphan listed; `**tearDown`** delete Scan Code row and any stray docs.
- **Step 3:** Commit: `test(integration): verify_scan_code_registry happy and orphan paths`.

---

### Task 6: Per-action `dispatch` integration

**Files:**

- Create: `asn_module/tests/integration/test_dispatch_actions_integration.py`
- **Step 1:** **PR + PI:** assert covered by Task 3–4 journey; either **import** the same test helper or add a thin test that only **dispatches** the two codes (skip if redundant—then document in file docstring).
- **Step 2:** **QI actions** (`create_stock_transfer`, `create_purchase_return`): reuse document builders from `asn_module.handlers.tests.test_quality_inspection` / `test_stock_transfer` / `test_purchase_return` to reach **submitted QI** linked to PR/ASN; `**get_or_create_scan_code`**; `**dispatch**` under Stock user; assert handler result and **transition log** if applicable.
- **Step 3:** `**confirm_putaway`:** reuse `handlers/tests/test_putaway.py` builders; dispatch from **Purchase Receipt** scan code.
- **Step 4:** **Subcontracting** (`create_subcontracting_dispatch`, `create_subcontracting_receipt`): reuse `test_subcontracting.py` patterns; if **fixture cost is too high** for one PR, implement **one** combined test with **clear `pytest.skip`** or `**unittest.skip**` citing ERPNext version/setup, and add **TODO** in plan appendix (do not block merge of Tasks 1–5).
- **Step 5:** Run `bench run-tests --app asn_module --module asn_module.tests.integration`.
- **Step 6:** Commit: `test(integration): dispatch coverage for registry actions`.

---

### Task 7: CI / runtime check (optional)

- **Step 1:** Record **before/after** `bench run-tests --app asn_module --lightmode` duration locally or from CI log.
- **Step 2:** If **>25%** slower or **>15 min** wall time, open follow-up issue or add **scheduled** job note in `docs/superpowers/specs/2026-04-04-realistic-integration-tests-design.md` §9 (no code required in this task).

---

## Verification commands

```bash
# Full app tests (as CI)
bench --site <yoursite> run-tests --app asn_module --lightmode

# Integration package only
bench --site <yoursite> run-tests --app asn_module --module asn_module.tests.integration

# Single file
bench --site <yoursite> run-tests --app asn_module --module asn_module.tests.test_e2e_flow
```

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-04-realistic-integration-tests.md`.

**1. Subagent-driven (recommended)** — one subagent per task, review between tasks.

**2. Inline execution** — run tasks in this session with checkpoints.

Which approach do you want?