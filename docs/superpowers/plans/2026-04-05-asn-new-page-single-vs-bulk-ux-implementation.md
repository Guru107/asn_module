# ASN New Page Single vs Bulk UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Frappe-like `/asn_new` page with tabbed Single/Bulk ASN creation, strict supplier-open-PO scoping, mandatory `sr_no` mapping, and all-or-nothing validations.

**Architecture:** Keep one website route (`/asn_new`) and split behavior by form mode (`single` vs `bulk`) in the page controller. Move validation/mapping into focused helpers so UI parsing, business validation, and document creation are independently testable. Use Link-like search endpoints for PO and item selection in Single mode, and strict CSV grouping by `supplier_invoice_no` in Bulk mode.

**Tech Stack:** Frappe website page controller (`templates/pages`), Python validation/services, Jinja + JS for tabbed UX, ERPNext Purchase Order/PO Item data, Frappe test framework (`FrappeTestCase`), bench test runner.

**Spec:** `docs/superpowers/specs/2026-04-05-asn-new-page-single-vs-bulk-ux-design.md`

---

## File map (target / current)


| Path                                                                         | Responsibility                                                                                              |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `asn_module/templates/pages/asn_new.html`                                    | Tabbed UI, form separation, Link-like controls, manual row interactions, mode-specific submit payloads.     |
| `asn_module/templates/pages/asn_new.py`                                      | Website `get_context`, mode routing, request parsing, success/error rendering, create+submit orchestration. |
| `asn_module/templates/pages/asn.py`                                          | Reused supplier and open-PO helper integration; ensure link from `/asn` targets `/asn_new`.                 |
| `asn_module/templates/pages/asn_new_services.py` (new)                       | Shared validation and mapping services (PO scope, `sr_no` resolution, invoice-group consistency, limits).   |
| `asn_module/templates/pages/asn_new_search.py` (new)                         | Whitelisted search endpoints for PO and item Link-like selectors on website page.                           |
| `asn_module/templates/pages/test_asn.py`                                     | List-page route expectation regression (`/asn_new`) and portal behavior checks.                             |
| `asn_module/templates/pages/test_asn_new.py`                                 | Single and bulk parsing/validation/creation tests, throughput limits, grouped error shape.                  |
| `asn_module/templates/pages/test_asn_new_search.py` (new)                    | Search endpoint scope tests (supplier open POs and PO item filtering).                                      |
| `docs/superpowers/specs/2026-04-05-asn-new-page-single-vs-bulk-ux-design.md` | Update only if implementation uncovers spec-required clarifications.                                        |


---

### Task 1: Stabilize tests baseline and remove duplication in `test_asn_new.py`

**Files:**

- Modify: `asn_module/templates/pages/test_asn_new.py`
- Test: `asn_module/templates/pages/test_asn_new.py`
- **Step 1: Inspect `test_asn_new.py` for duplicate class/content blocks**

Run: `rg -n "class TestASNNewPortalPage" asn_module/templates/pages/test_asn_new.py`

Expected: identify duplicate test-class definitions if present.

- **Step 2: Write/keep one failing test for mode routing contract**

Add test scaffold (example):

```python
def test_post_rejects_mixed_or_missing_mode_payload():
    ...
```

Expected initially: FAIL (until POST submit mode handling is implemented).

- **Step 3: Remove duplicate test block and keep one canonical test class**

Ensure test names are unique and deterministic.

- **Step 4: Run focused test module**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: still FAIL on new mode test, no import/duplicate issues.

- **Step 5: Commit**

```bash
git add asn_module/templates/pages/test_asn_new.py
git commit -m "test(portal): normalize asn_new test module baseline"
```

---

### Task 2: Add shared validation/mapping service for Single and Bulk flows

**Files:**

- Create: `asn_module/templates/pages/asn_new_services.py`
- Modify: `asn_module/templates/pages/asn_new.py`
- Test: `asn_module/templates/pages/test_asn_new.py`
- **Step 1: Write failing tests for service-level rules**

Add tests for:

- open PO scope (`docstatus=1`, status in `To Receive`, `To Receive and Bill`)
- mandatory `sr_no`
- resolver by `purchase_order + sr_no`
- resolver failure when `purchase_order + sr_no` matches zero rows
- resolver failure when `purchase_order + sr_no` matches multiple rows
- `item_code` mismatch rejection
- `qty > 0`
- `rate >= 0`
- row `qty` cannot exceed remaining receivable quantity on resolved PO item
- duplicate `(purchase_order, sr_no)` in same invoice group rejection
- group consistency normalization and mismatch errors
- limits (rows > 5000, groups > 500)
- **Step 2: Run tests to verify failures**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: FAIL with missing service behavior.

- **Step 3: Implement minimal service module**

Implement focused helpers (example names):

- `validate_open_po_scope(...)`
- `resolve_po_item_by_sr_no(...)`
- `validate_bulk_group_consistency(...)`
- `enforce_bulk_limits(...)`
- `build_error_entry(...)`
- **Step 4: Wire `asn_new.py` to call service helpers**

Replace inline validation branches with service calls while preserving response contract (417 with structured errors for validation).

- **Step 5: Re-run focused tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: PASS for new shared-validation tests.

- **Step 6: Commit**

```bash
git add asn_module/templates/pages/asn_new_services.py asn_module/templates/pages/asn_new.py asn_module/templates/pages/test_asn_new.py
git commit -m "feat(portal): add shared asn_new validation and sr_no resolver services"
```

---

### Task 3: Implement tabbed `/asn_new` page with mode separation

**Files:**

- Modify: `asn_module/templates/pages/asn_new.html`
- Modify: `asn_module/templates/pages/asn_new.py`
- Test: `asn_module/templates/pages/test_asn_new.py`
- **Step 1: Add failing tests for mode-separated form handling**

Cover:

- `mode=single` accepted for single form payload
- `mode=bulk` accepted for bulk CSV payload
- mixed payload rejected
- missing mode rejected
- permission failure returns HTTP 403 for non-supplier/forbidden user
- **Step 2: Run tests to verify failures**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: FAIL on mode separation assertions.

- **Step 3: Update HTML to tabbed layout**

Implement:

- Single tab form (manual rows only)
- Bulk tab form (CSV only)
- explicit hidden mode inputs
- header-level fields in both tabs (`lr_no`, `lr_date`, `transporter_name`, invoice/date, expected delivery)
- separate `<form>` elements per tab (no shared hidden inputs between forms)
- explicit success behavior: single mode redirects to created ASN route
- spec §8 error UX elements:
  - single-tab top alert + row-labeled errors (`Manual row N: ...`)
  - bulk errors grouped by invoice and row
  - bulk failure summary text indicating “no ASNs created”
- **Step 4: Update controller to dispatch by mode**

Ensure single and bulk paths are isolated and produce mode-specific success/error rendering.

- **Step 5: Run tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: PASS for mode routing and tab contract tests.

- **Step 6: Commit**

```bash
git add asn_module/templates/pages/asn_new.html asn_module/templates/pages/asn_new.py asn_module/templates/pages/test_asn_new.py
git commit -m "feat(portal): split asn_new into single and bulk tab workflows"
```

---

### Task 4: Add Link-like PO and item search endpoints for Single tab

**Files:**

- Create: `asn_module/templates/pages/asn_new_search.py`
- Modify: `asn_module/templates/pages/asn_new.py`
- Modify: `asn_module/templates/pages/asn_new.html`
- Test: `asn_module/templates/pages/test_asn_new_search.py`
- **Step 1: Write failing tests for search endpoint scope**

Test:

- PO search returns only supplier open POs
- item search requires selected row PO
- item search only returns items from that PO
- non-supplier and out-of-scope queries denied
- **Step 2: Run endpoint tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_search --lightmode`

Expected: FAIL (module/endpoints missing).

- **Step 3: Implement whitelisted search functions**

Use existing supplier resolution helper and service-layer PO constraints.

- **Step 4: Hook frontend controls to these endpoints**

Implement Link-like UX behavior:

- PO typeahead + selected chips
- row PO selector filtered from chips
- row item selector filtered by row PO
- on row PO change clear `sr_no`, `item_code`, `uom`, `rate`
- **Step 5: Re-run search tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_search --lightmode`

Expected: PASS.

- **Step 6: Commit**

```bash
git add asn_module/templates/pages/asn_new_search.py asn_module/templates/pages/asn_new.py asn_module/templates/pages/asn_new.html asn_module/templates/pages/test_asn_new_search.py
git commit -m "feat(portal): add link-style po and item search for single asn tab"
```

---

### Task 5: Implement Bulk CSV multi-ASN grouping and creation contract

**Files:**

- Modify: `asn_module/templates/pages/asn_new.py`
- Modify: `asn_module/templates/pages/asn_new_services.py`
- Modify: `asn_module/templates/pages/test_asn_new.py`
- **Step 1: Add failing tests for bulk grouping behavior**

Cover:

- one ASN per unique `supplier_invoice_no`
- identical invoice-header metadata required per group
- mismatch reporting emits one structured error per offending row with expected vs found values
- strict CSV header and exact column-order validation
- structured 417 errors with `row_number`, `invoice_no`, `field`, `message`
- no document creation on any row/group failure
- UOM is derived from resolved PO item (no CSV UOM input)
- **Step 2: Run failing tests**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: FAIL on grouping/contract expectations.

- **Step 3: Implement grouping + creation orchestration**

Implement:

- normalize and group rows
- validate all groups first
- create+submit ASNs for all groups only after validation passes
- render inline success summary with created ASN names/count
- emit row-level grouped consistency errors (field-scoped, expected vs found)
- enforce strict bulk CSV headers/order before grouping stage
- render grouped bulk errors in invoice->row presentation and include “no ASNs created” message on any validation failure
- **Step 4: Re-run test module**

Run: `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`

Expected: PASS for bulk grouping and all-or-nothing behaviors.

- **Step 5: Commit**

```bash
git add asn_module/templates/pages/asn_new.py asn_module/templates/pages/asn_new_services.py asn_module/templates/pages/test_asn_new.py
git commit -m "feat(portal): support bulk multi-asn upload grouped by supplier invoice"
```

---

### Task 6: Regressions, lint/test sweep, and docs alignment

**Files:**

- Modify: `asn_module/templates/pages/test_asn.py` (if route/assertions need updates)
- Modify: `docs/superpowers/specs/2026-04-05-asn-new-page-single-vs-bulk-ux-design.md` (only if clarifications discovered)
- **Step 1: Run targeted portal tests**

Run:

- `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn --lightmode`
- `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new --lightmode`
- `bench --site dev.localhost run-tests --app asn_module --module asn_module.templates.pages.test_asn_new_search --lightmode`

Expected: PASS.

- **Step 2: Run broader app smoke tests (existing suite path)**

Run: `bench --site dev.localhost run-tests --app asn_module --lightmode`

Expected: PASS (or known unrelated baseline failures documented before merge).

- **Step 3: Lint edited files**

Run:

- `ruff check asn_module/templates/pages/`
- `npx eslint asn_module/templates/pages/ --quiet` (if JS extraction occurs outside template; otherwise skip with note)

Expected: no new lint issues.

- **Step 4: Commit**

```bash
git add asn_module/templates/pages/test_asn.py asn_module/templates/pages/test_asn_new.py asn_module/templates/pages/test_asn_new_search.py docs/superpowers/specs/2026-04-05-asn-new-page-single-vs-bulk-ux-design.md
git commit -m "test(portal): finalize asn_new single-bulk regression coverage"
```

---

## Acceptance Checklist

- `/asn` New ASN button opens `/asn_new`.
- `/asn_new` displays two tabs with separate submit paths (`mode=single|bulk`).
- Tabs use separate form elements; switching tabs does not leak hidden inputs across modes.
- Single tab enforces selected open PO scope, mandatory `sr_no`, and row dependency clearing.
- Single submit redirects to the created ASN route.
- Bulk tab accepts strict schema and creates multiple ASNs by invoice grouping.
- Bulk enforces strict CSV header and exact column order.
- Bulk consistency mismatches emit one row-level error per offending row with expected vs found details.
- Single tab shows top alert plus `Manual row N` messages on row validation failures.
- Bulk tab shows grouped invoice/row error presentation and explicit “no ASNs created” summary on failure.
- All validation failures are all-or-nothing and row/invoice-specific.
- Permission failures return HTTP 403.
- All portal tests for `asn`, `asn_new`, and `asn_new_search` pass under bench.

