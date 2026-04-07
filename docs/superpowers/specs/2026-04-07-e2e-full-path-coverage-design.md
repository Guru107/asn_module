# ASN Module E2E — Full Path Coverage Plan

**Status:** Draft  
**Created:** 2026-04-07

---

## 1. Goals

- Cover **every public page and desk route** in the ASN module with at least one Cypress smoke test
- Expand nightly suite to cover **all code paths + assertions** (happy paths, error states, edge cases) on **both Frappe v15 and v16**
- Tests run on both Frappe v15/v16 matrix rows; failures on either version are blocking
- Portal data creation uses a hybrid approach: server-seeded reference data + real UX flows for portal-facing paths

---

## 2. Scope

### 2.1 Pages in scope

| Page | Route | Suite | Notes |
|------|-------|-------|-------|
| ASN list | `/asn` | smoke + nightly | Already covered |
| Scan station | `/scan-station` | smoke + nightly | Already covered |
| ASN portal (view) | `/asn` (portal) | smoke + nightly | Portal view of ASN list |
| New ASN (single) | `/purchasing/asn-new` | smoke + nightly | Portal creation, single mode |
| New ASN (bulk) | `/purchasing/asn-new` | smoke + nightly | Same route, bulk mode |
| ASN New Services | `/purchasing/asn-new-services` | smoke + nightly | Invoice validation helpers |
| ASN detail (desk) | `/asn/<name>` | smoke | Open submitted ASN, verify fields |
| Transition trace (desk) | `/report/asn-item-transition-trace` | smoke | Report page load + basic filter |

### 2.2 Out of scope

- Playwright (not used in this codebase)
- Non-Cypress E2E tooling
- Changes to Python unit/integration test coverage

---

## 3. Architecture

### 3.1 Directory structure

```
cypress/
  support/
    e2e.js                    ← already exists, loads Frappe support
  integration/
    smoke/
      asn_desk_smoke.js        ← expand: basic list + detail
      scan_station_smoke.js    ← expand: happy path scan
      asn_portal_smoke.js      ← NEW: portal list, detail view
      asn_new_portal_smoke.js  ← NEW: single + bulk creation flows
      asn_new_services_smoke.js ← NEW: service validation flows
      transition_trace_smoke.js ← NEW: report page
    nightly/
      asn_desk_nightly.js      ← expand: error states, filtered views
      scan_station_nightly.js  ← expand: all error states
      asn_portal_nightly.js    ← expand: portal error flows
      asn_new_portal_nightly.js ← expand: all validation error branches
      asn_new_services_nightly.js ← expand: all helper error paths
```

### 3.2 Seed helpers (`asn_module/utils/cypress_helpers.py`)

Existing helpers:
- `seed_minimal_asn()` — creates submitted ASN + PO
- `seed_scan_station_context()` — creates ASN + scan code for dispatch flow

New helpers needed for portal and report coverage:
- `seed_supplier_context()` — creates supplier + portal user + PO (for portal pages)
- `seed_asn_with_items()` — creates ASN with multiple items (for detail/transition trace)
- `seed_quality_inspection_context()` — creates PO, ASN, PR, QI (for QI-related error paths)

### 3.3 Data strategy (Hybrid)

**Server-seeded (via `cy.call()`):**
- Supplier + portal user + open PO
- ASN header + items (for desk detail view)
- Scan code + dispatched ASN (for scan station)

**UX-flow (real user steps):**
- Portal ASN creation (single + bulk): fill form, submit, verify success/error
- All validation error states on portal pages

---

## 4. Test Specifications

### 4.1 Smoke suite (critical paths only)

#### `asn_desk_smoke.js`
- Opens ASN list without console errors *(already exists)*
- **New:** opens ASN detail for a submitted ASN, shows key fields
- **New:** shows no-access message for non-portal users on portal route

#### `scan_station_smoke.js`
- Renders scan input, rejects legacy token *(already exists)*
- **New:** after seeding, accepts valid scan code and shows success feedback

#### `asn_portal_smoke.js` (NEW)
- Portal user can see their ASN list
- Opens ASN detail from portal list

#### `asn_new_portal_smoke.js` (NEW)
- Single mode: rejects empty form, accepts valid single ASN submission
- Bulk mode: rejects empty CSV, accepts valid bulk CSV submission

#### `asn_new_services_smoke.js` (NEW)
- Invoice number reuse is rejected with clear error
- Quantity exceeding remaining is rejected
- All PO SR No duplicates in same invoice group rejected

#### `transition_trace_smoke.js` (NEW)
- Report page loads and renders
- Basic date filter works
- No errors in console on load

### 4.2 Nightly suite (all error branches)

#### `asn_desk_nightly.js`
- Seeded ASN appears in list view
- Filter by status (Open, Submitted, Received, Closed)
- Open ASN detail shows correct fields

#### `scan_station_nightly.js`
- All invalid token formats rejected with specific messages
- Unknown scan code rejected
- Valid scan code → success + scan result displayed
- Dispatch flow with accepted QI
- Dispatch flow with rejected QI → error state

#### `asn_portal_nightly.js`
- Non-supplier user denied access
- ASN with status Closed hides submit action
- ASN items show correct remaining qty

#### `asn_new_portal_nightly.js`
- Single mode: each PortalValidationError branch covered
  - Missing supplier
  - Zero qty
  - Negative rate
  - Duplicate PO/SR No in same invoice
- Bulk mode: each validation branch
  - CSV with missing required columns
  - Row with qty > remaining on PO
  - Duplicate PO/SR No across rows
  - Supplier invoice amount mismatch

#### `asn_new_services_nightly.js`
- `validate_supplier_invoices_not_reused` — duplicate invoice rejected
- `validate_qty_within_remaining` — over-limit rejected
- `validate_no_duplicate_po_sr_no` — duplicate in group rejected
- `validate_invoice_group_consistency` — field mismatch rejected
- `fetch_purchase_order_items` — empty list, valid PO, filtered results
- `parse_required_supplier_invoice_amount` — empty, zero, negative, valid

### 4.3 Version-specific routing

- v15: `routePrefix = "app"` → URLs start with `/app/...`
- v16: `routePrefix = "app"` → URLs start with `/app/...` (confirmed working for both in current suite)
- Helper: `const route = (path) => \`/${Cypress.env("routePrefix")}/\${path.replace(/^\\//, "")}\``

---

## 5. Seed Helper Specifications

### 5.1 `seed_supplier_context()`

Creates:
- Supplier doc
- Portal user with Supplier role
- 2 POs with items (open, partially received)

Returns: `{ supplier, portal_user, purchase_orders: [{name, items}] }`

### 5.2 `seed_asn_with_items()`

Creates:
- Supplier + portal user
- PO with multiple items
- ASN with multiple items (submitted)

Returns: `{ asn_name, item_count, items: [{name, item_code, qty}] }`

### 5.3 `seed_quality_inspection_context()`

Creates:
- PO, ASN, PR (submitted), QI (Accepted + Rejected per item)

Returns: `{ asn_name, pr_name, qi_accepted, qi_rejected }`

---

## 6. Frappe v15 / v16 Matrix

- Both `frappe_version: "15"` and `"16"` rows run all smoke + nightly specs
- Smoke: `E2E_SUITE=smoke`, runs on PR + workflow_dispatch
- Nightly: `E2E_SUITE=nightly`, runs on schedule (cron `0 2 * * *`)
- Route prefix: `"app"` for both versions (confirmed working)
- Electron browser via `--browser electron` in `run_ephemeral_e2e.sh`

---

## 7. Acceptance Criteria

- Every page in scope has ≥1 smoke test and ≥1 nightly test
- All error branches from `PortalValidationError` callers have nightly coverage
- Smoke suite passes on both v15 and v16 for every PR
- Nightly suite passes on both v15 and v16 on every scheduled run
- Seed helpers are reusable across all specs
- No test is order-dependent (each spec seeds its own data)

---

## 8. File changes

| File | Change |
|------|--------|
| `asn_module/utils/cypress_helpers.py` | Add 3 new seed helpers |
| `cypress/integration/smoke/asn_desk_smoke.js` | Expand (detail view) |
| `cypress/integration/smoke/scan_station_smoke.js` | Expand (valid scan) |
| `cypress/integration/smoke/asn_portal_smoke.js` | **NEW** |
| `cypress/integration/smoke/asn_new_portal_smoke.js` | **NEW** |
| `cypress/integration/smoke/asn_new_services_smoke.js` | **NEW** |
| `cypress/integration/smoke/transition_trace_smoke.js` | **NEW** |
| `cypress/integration/nightly/asn_desk_nightly.js` | Expand |
| `cypress/integration/nightly/scan_station_nightly.js` | Expand (all error states) |
| `cypress/integration/nightly/asn_portal_nightly.js` | **NEW** |
| `cypress/integration/nightly/asn_new_portal_nightly.js` | **NEW** |
| `cypress/integration/nightly/asn_new_services_nightly.js` | **NEW** |

---

## 9. Next step

Create implementation plan under `docs/superpowers/plans/` and execute task-by-task using subagent-driven development.
