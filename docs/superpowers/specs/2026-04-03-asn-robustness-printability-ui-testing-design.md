# ASN Robustness, Printability, and UI Testing Design

## Overview

This design defines a three-subproject sequence to harden ASN module integration behavior, improve code printability/scannability on supplier invoices, and add native Cypress UI coverage.

User decisions captured:

- Prioritize code format and printability first.
- Assume scanner capability is unknown/uncontrolled in supplier environments.
- No backward compatibility required for previously generated QR codes.
- Prefer smallest printable payload (server lookup model).
- Add item-level transition traceability.
- Keep ASN form compact with drill-down into a report view.
- Use report-style full trace view from ASN (not a custom Desk page).

## Scope and Sequencing

### Subproject 1 (first): Compact scan code format and printability

Replace payload-heavy token encoding with short opaque scan codes for new documents only.

### Subproject 2 (second): Integration hardening and transition traceability

Add item-level transition logs, ASN summary visibility, and report-based deep trace with filtering/search.

### Subproject 3 (third): Cypress UI tests and CI integration

Add critical-user-journey UI tests with bench-native Cypress execution and CI gating.

---

## Subproject 1: Compact Code Format + Printability

## Architecture

Introduce a new registry as source of truth for printable scan codes:

- `Scan Code Registry` (new doctype/table):
  - `scan_code` (unique short opaque ID)
  - `symbology` (`qr`, `code128`)
  - `action_key`
  - `source_doctype`
  - `source_name`
  - `status` (`active`, `used`, `revoked`, `expired`)
  - `generated_on`, `generated_by`
  - optional operational fields: `expires_on`, `last_scanned_on`, `scan_count`

Dispatch resolves from `scan_code` to action/source metadata through this registry.

## Dispatch Contract

### URL shape

- QR target URL template: `{site}/api/method/asn_module.qr_engine.dispatch.dispatch?code={scan_code}`
- Barcode payload: `{scan_code}` (raw)

### Action map (v1)

`action_key` values are controlled by `register_actions()` and must match existing handler contracts:

- `create_purchase_receipt` -> `ASN`
- `create_stock_transfer` -> `Quality Inspection`
- `create_purchase_return` -> `Quality Inspection`
- `create_purchase_invoice` -> `Purchase Receipt`
- `confirm_putaway` -> `Purchase Receipt`
- `create_subcontracting_dispatch` -> `Subcontracting Order`
- `create_subcontracting_receipt` -> `Subcontracting Order`

### Re-scan policy (v1)

- Re-scan-safe when status is `used`: `confirm_putaway`
- Not re-scan-safe by default: all document-creation actions (`create_*`)

### Validation order

Dispatch must validate in strict sequence:

1. code exists and resolves to active registry row
2. status checks (`active` only unless explicitly re-scan-safe action)
3. expiry checks
4. role authorization against action registry
5. source consistency between action mapping and resolved source doctype/name
6. handler execution

## Input Contract (breaking by design)

No legacy token compatibility for newly generated codes:

- Supported inputs:
  - `code=<scan_code>` in URL
  - raw short code
- Unsupported:
  - token-style payloads (`token=...`)
  - direct image file URLs (`/files/...png`)

## Generation Flow

1. Trigger code generation on defined events only:
  - ASN `on_submit`: create initial scan code for `create_purchase_receipt`
  - Purchase Receipt `on_submit`: create follow-up scan codes for invoice/putaway actions
  - Quality Inspection `on_submit`: create follow-up scan codes for transfer/return actions
  - Subcontracting Order `on_submit` and Subcontracting Dispatch `on_submit`: create next-step scan codes
2. Generate short unique `scan_code` (collision-checked).
3. Persist registry row with `status=active`.
4. Render:
  - QR: compact URL containing only `code`
  - Barcode: raw short code
5. Attach rendered assets and show human-readable code text.

## Dispatch Flow

1. Parse incoming scan input into normalized `scan_code`.
2. Resolve registry row.
3. Validate: existence, status, optional expiry, role authorization, source/action consistency.
4. Execute existing handler path for mapped action.
5. Update operational metadata (`scan_count`, `last_scanned_on`, optional status transitions).
6. Emit stable user-facing errors and structured logs.

### Authorization and lifecycle rules

- A scan executes only when user roles intersect with action `allowed_roles`.
- Status semantics:
  - `active`: executable
  - `used`: executable only for actions explicitly marked as re-scan-safe; otherwise blocked
  - `revoked` / `expired`: blocked
- Blocked scans must return stable, non-technical error codes/messages.

## Printability Specification

Given unknown scanner capability, encode both machine and human fallback:

- Short code format:
  - fixed-length uppercase compact alphabet excluding ambiguous characters.
  - display grouping for humans (e.g., `ABCD-EFGH-IJKL`) while barcode encodes raw value.
- Barcode:
  - Code128, tuned for invoice column width.
  - enforce quiet zones and max width thresholds.
- QR:
  - compact URL with only `code`.
  - size tuned for invoice print area.
- Display:
  - always print human-readable code under barcode/QR.
  - include fallback instruction for manual entry.

## Subproject 1 Acceptance

- New generated labels scan successfully from QR and barcode.
- Invoice print layout remains readable/scannable.
- Invalid input classes return clear errors without traceback leakage.

---

## Subproject 2: Integration Hardening + Traceability

## Transition Logging Model (item-level)

Add `ASN Transition Log` (immutable event rows):

- keys: `asn`, `asn_item`, `item_code`
- transition fields: `state`, `status`
- references: `ref_doctype`, `ref_name`
- audit: `event_ts`, `actor`
- diagnostics: `error_code`, `details`
- actor semantics:
  - user-triggered event: `frappe.session.user`
  - system-triggered event: `System` (or integration user), never null

Canonical states include (initial set):

- `ASN_GENERATED`
- `PR_CREATED_DRAFT`
- `PR_SUBMITTED`
- `QI_CREATED`, `QI_SUBMITTED` (where applicable)
- `PUTAWAY_CONFIRMED`
- `PI_CREATED_DRAFT` (and optional `PI_SUBMITTED`)
- `PURCHASE_RETURN_CREATED`, `STOCK_TRANSFER_CREATED`
- `SUBCON_DISPATCH_CREATED`, `SUBCON_RECEIPT_CREATED`
- explicit failure states:
  - `PR_CREATE_FAILED`
  - `PR_SUBMIT_FAILED`
  - `PI_CREATE_FAILED`
  - `ACTION_EXECUTION_FAILED` (generic fallback)

## Emission Rules

- Emit one row per item per meaningful transition.
- Prevent duplicates with idempotency key:
  - `(asn, asn_item, state, ref_doctype, ref_name)`
- For document-level operations affecting multiple lines, emit per impacted ASN item.
- Idempotency edge cases:
  - same state with new reference (`ref_name` changed): emit a new row
  - same state + same reference replay: dedupe
  - cancellation/replacement events: emit explicit new transition rows, do not mutate old rows

## ASN UX (compact + drill-down)

On ASN form:

- read-only summary table with latest state per item:
  - `Item`, `Current State`, `Status`, `Ref`, `Updated`
- button: **Open Full Trace View**

Drill-down destination:

- Script Report: `ASN Item Transition Trace`
- prefilled with ASN filter from form.
- report permission: Stock User/Stock Manager (+ Accounts roles where invoice transitions are visible).

## Report Contract

Filters:

- ASN, Item Code, State, Status, Ref DocType, Ref Name, date range, failures-only

Columns:

- Event Time, ASN, ASN Item, Item Code, State, Status, Reference, Actor, Error Code, Details

Capabilities:

- search, sort, pagination, export
- default sort: `Event Time desc`
- max row guard per page to prevent heavy render stalls (server-side pagination required)

Performance:

- indexed query paths for ASN/time/item/state/ref fields

## Integration Guardrails

- Registry integrity verification command and optional repair path.
- Strict scan input and dispatch validation with stable user-facing errors.
- Singleton/test isolation rules to prevent test data pollution in shared registries.
- Required test isolation outcome: any test mutating singleton registries must snapshot and restore state
(or run against an isolated disposable site) before suite completion.

## Subproject 2 Acceptance

- Item-level transition logs are visible in ASN summary and report.
- Integration failures produce diagnosable, structured events.
- Registry/config drift is detectable and recoverable.

---

## Subproject 3: Cypress UI Testing (bench-native)

## Initial Critical Journeys

1. Scan Station renders and remains interactive.
2. Valid code scan routes to created document.
3. Invalid scan inputs show friendly, actionable messages.
4. ASN form PO item population flow remains stable (no stuck overlay).
5. ASN submit flow succeeds and emits expected transition events.
6. ASN summary and full trace report navigation works from form button.

Journey 5 verification approach:

- Cypress verifies user-visible outcome (submit success + summary refresh).
- Transition emission correctness is additionally asserted via API-backed checks in the same test run
(query transition rows for ASN/item/state), so UI tests do not rely on visual inference alone.

## CI Integration

- Add/confirm `bench run-ui-tests asn_module` job in CI for this app.
- Keep a mandatory smoke subset for PR gating.
- Archive screenshots/videos/logs on failures.

## Subproject 3 Acceptance

- Cypress smoke suite is stable in CI.
- Failures are diagnosable via artifacts.
- UI regressions in scan and ASN core journeys are caught automatically.

---

## Out of Scope

- Backward support for previously generated token-based QR codes.
- Full historical migration of old scans into new code registry.
- Large unrelated refactors not required for these three subprojects.

## Risks and Mitigations

- **Risk:** code collision in short IDs  
**Mitigation:** unique constraint + retry loop + collision tests.
- **Risk:** printability still poor on some invoice templates  
**Mitigation:** enforce rendering thresholds and add manual print checklist.
- **Risk:** transition event overlogging/noise  
**Mitigation:** idempotency keys and canonical state definitions.
- **Risk:** flaky UI tests  
**Mitigation:** smoke-first suite, stable selectors, condition-based waits, CI artifacts.

## Implementation Readiness

This spec is ready for implementation planning as three sequential plans:

1. Compact code format + printability
2. Integration hardening + traceability
3. Cypress UI tests + CI gating