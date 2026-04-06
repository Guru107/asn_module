# Integration Test Suite — Coverage Gap Closure

## Goal

Raise Python line coverage from **92.7%** to **~94-95%** by adding targeted
integration tests that exercise uncovered error branches in existing modules.

Coverage is measured via Frappe's `--coverage` flag (coverage.xml, Cobertura format).

## What Is an Integration Test Here

A `FrappeTestCase` that creates real documents in the database and exercises
the full dispatch/handler stack with real ERPNext transactions. Follows the same
patterns as the existing `tests/integration/` suite:

- Uses `before_tests()` for test fixture bootstrap
- Uses `integration_user_context()` for permission-accurate session switching
- Uses `real_asn_attachment_context()` for ASN submission with attachments
- Uses `register_actions()` to seed the QR Action Registry

## NOT Covered by Integration Tests

The following cannot be covered by integration tests:
- **Module-level definitions** (imports, constants, function def lines) — executed at module load, not test execution
- **`cypress_helpers.py`** — E2E seeding helpers called via HTTP, not core business logic
- **`custom_fields/*.py`** — app installation hooks

Realistic ceiling: **~94-95%**

---

## Files to Create

### 1. `asn_module/handlers/tests/test_purchase_return_errors.py`

Covers `asn_module/handlers/purchase_return.py` error branches.

**Uncovered lines:**
- L32-35: loop through `original_pr.items` looking for `qi_pr_item` match (success path — QI item found in PR)
- L41-47: `elif len(matching_rows) > 1` → `frappe.throw` (ambiguous QI source — shared logic also in stock_transfer)
- L50: `frappe.throw(_("Item {0} not found in {1}")...)` (QI item not in PR)

**Test cases:**
- `test_qi_item_found_in_pr_returns_that_item` — QI `purchase_receipt_item` set to a valid PR item row → `source_row` found, no error
- `test_qi_item_not_found_in_pr_raises_item_not_found` — QI `purchase_receipt_item` set to non-existent PR item → `ItemNotFoundError` at L50
- `test_ambiguous_qi_raises_validation_error` — QI without `purchase_receipt_item` matches multiple PR items → `frappe.ValidationError`

**Note:** The `elif len(matching_rows) > 1` branch (L41-47) may already be exercised by `test_rejects_ambiguous_purchase_receipt_item_match` in `test_stock_transfer.py` (shared handler logic). Verify before adding duplicate.

**Fixtures:** Real Purchase Receipt with items, Quality Inspection with specific `purchase_receipt_item` field set via direct doc assignment.

---

### 2. `asn_module/handlers/tests/test_stock_transfer_errors.py`

Covers `asn_module/handlers/stock_transfer.py` error branches.

**Uncovered lines:**
- L17: `frappe.throw(_("Quality Inspection {0} is not Accepted..."))` (QI not Accepted)
- L30-33: loop through `purchase_receipt.items` looking for `qi_pr_item` match
- L48: `frappe.throw(_("Item {0} not found in {1}")...)` (item not in PR)

**Test cases:**
- `test_rejected_qi_raises_validation_error` — QI status is "Rejected" → `frappe.ValidationError` at L17
- `test_qi_item_found_in_pr_returns_that_item` — QI `purchase_receipt_item` set to valid PR item → `source_row` found
- `test_qi_item_not_found_in_pr_raises` — QI `purchase_receipt_item` set to non-existent PR item → `ItemNotFoundError` at L48

**Fixtures:** Purchase Receipt + Quality Inspection (Accepted for success path, Rejected for error path).

---

### 3. `asn_module/qr_engine/tests/test_dispatch_errors.py`

Covers `asn_module/qr_engine/dispatch.py` error branches.

**Uncovered lines:**
- L65: `raise frappe.ValidationError("Invalid handler result: expected a dict")`
- L80-81: bare `except Exception: pass` (error-result handler branch)
- L145: `code = frappe.form_dict.get("code")` (from_request path when code is None)
- L157: `raise ScanCodeNotFoundError(_("Missing scan code."))`
- L161: `raise ScanCodeNotFoundError(_("Unknown or invalid scan code."))`

**Test cases:**
- `test_handler_returning_string_raises_validation_error` — patch handler to return a string instead of dict → L65
- `test_handler_returning_error_dict_swallows_exception` — patch handler to return `{"success": False, "error": "..."}` → L80-81, verify via `frappe.log_error`
- `test_dispatch_from_request_missing_code_raises` — call `dispatch()` without code arg (from_request path) → L157
- `test_dispatch_from_request_unknown_code_raises` — call with invalid scan code via from_request path → L161
- `test_dispatch_unknown_scan_code_raises` — call `dispatch()` with non-existent scan code

**Feasibility note:** Testing the `from_request` path (L145: `code = frappe.form_dict.get("code")`) requires either mocking `frappe.form_dict` or calling `dispatch()` via `frappe.call()` through the request stack. If mocking `frappe.form_dict` is not feasible in a FrappeTestCase, these tests may need to be deferred or implemented via a separate HTTP-level integration test.

---

### 4. `asn_module/templates/pages/tests/test_asn_new_services_integration.py`

Covers `asn_module/templates/pages/asn_new_services.py` helper function paths.

**Actual function names (verified against source):**
- `fetch_purchase_order_items(purchase_orders: list[str])` — L211, returns `(rows_by_key, remaining_qty_by_name)`
- `get_supplier_open_purchase_orders(supplier: str)` — L80, returns dict of PO name → row
- `validate_qty_within_remaining(...)` — L292, raises `PortalValidationError` at L303
- `validate_invoice_group_consistency(...)` — L359, raises at L382
- `validate_no_duplicate_po_sr_no(...)` — L385, raises at L404

**Uncovered lines:**
- L214-215: `if not purchase_orders: return {}, {}`
- L217-228: `frappe.get_all` + `po_item_qty_by_name` + `_get_shipped_qty_by_po_item` + `remaining_qty_by_name`
- L230-235: `rows_by_key` group-by `(parent, sr_no)` tuple
- L303: `raise PortalValidationError` (qty exceeds remaining)
- L382: `raise PortalValidationError` (inconsistent group)
- L404: `raise PortalValidationError` (duplicate PO sr_no)

**Test cases:**
- `test_fetch_purchase_order_items_empty_list_returns_empty` — L214-215
- `test_fetch_purchase_order_items_returns_grouped_rows_and_remaining_qty` — L217-235
- `test_validate_qty_within_remaining_raises_on_excess` — L303
- `test_validate_invoice_group_consistency_raises_on_mismatch` — L382
- `test_validate_no_duplicate_po_sr_no_raises_on_duplicate` — L404

---

### 5. `asn_module/report/tests/test_transition_trace_filters.py`

Covers `asn_module.asn_module.report.asn_item_transition_trace.asn_item_transition_trace`
(module path: `asn_module/asn_module/report/asn_item_transition_trace/asn_item_transition_trace.py`).

**Uncovered lines:**
- L43: `q = q.where(Log.ref_doctype == filters["ref_doctype"])`
- L45: `q = q.where(Log.ref_name == filters["ref_name"])`
- L47: `q = q.where(Log.event_ts >= get_datetime(filters["from_date"]))`
- L49: `q = q.where(Log.event_ts <= get_datetime(filters["to_date"]))`
- L51: `q = q.where(Log.transition_status == "Error")`
- L53-61: search text LIKE filter (`pat = f"%{search}%"` → LIKE on state, item_code, ref_name, details)

**Test cases:**
- `test_execute_filters_by_ref_doctype` — emit transitions with ref_doctype "Purchase Receipt" and "ASN", filter by one
- `test_execute_filters_by_ref_name` — emit two transitions with different ref_names, filter by one
- `test_execute_filters_by_date_range_excludes_outside` — emit transition, filter with before/after range
- `test_execute_filters_by_error_status_only` — emit OK and Error transitions, filter by "Error"
- `test_execute_filters_by_search_text_partial_match` — transition ref_name has "ABC-123", search "BC-1" matches

**Approach:** Extends existing `_ReportTestBase` from `test_transition_trace_report.py`. Emit transitions with controlled ref_doctype/ref_name/timestamps and verify `execute()` filtering.

---

### 6. `asn_module/qr_engine/tests/test_scan_codes_integration.py`

**Status:** Tests for `verify_registry_row_points_to_existing_source` with empty source_name and DB exception **already exist** in `test_scan_codes.py` (lines 229-242, hits=1). No new file needed for this module.

Verify with coverage report after adding other tests before deciding if additional scan_codes coverage work is needed.

---

## Coverage Impact Estimate

| File | New Tests | Lines Gained | Notes |
|---|---|---|---|
| `purchase_return.py` | 2-3 | +4-6 | Some branches shared with stock_transfer |
| `stock_transfer.py` | 3 | +5-6 | |
| `dispatch.py` | 5 | +7 | |
| `asn_new_services.py` | 5 | +10-14 | |
| `transition_trace.py` | 5 | +7 | |
| **Total** | **~20** | **~33-40** | |

**Realistic final coverage: ~94-95%**

Remaining uncovered lines (~130) are module-level defs (executed at import time),
`cypress_helpers.py` (E2E seeding), and `custom_fields/*.py` (installation hooks).

## Constraints

- All tests must pass with `--lightmode` (no ERPNext fiscal year bootstrap)
- Use `FrappeTestCase` as base class
- Clean up created documents in `tearDownClass`
- Tests must not depend on execution order
- Do not duplicate existing tests already in `test_scan_codes.py` or `test_stock_transfer.py`
- Verify coverage delta with Frappe's `--coverage` flag after implementation
