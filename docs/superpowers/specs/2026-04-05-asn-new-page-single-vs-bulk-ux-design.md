# ASN Portal New Page — Single vs Bulk UX Design

**Status:** Approved (brainstorming session, 2026-04-05)

---

## 1. Goals

- Improve `/asn_new` UX to stay close to Frappe interaction patterns.
- Split ASN creation into two clear user intents on one page:
  - **Single ASN**
  - **Bulk ASN Upload**
- Keep supplier scope restrictions strict:
  - only supplier-owned **open Purchase Orders**
  - only PO items from the chosen PO
- Preserve strict validation and all-or-nothing server behavior.

---

## 2. Non-goals

- No desk-form migration (`/app/asn/new`) in this phase.
- No new doctype creation for transporter/logistics metadata in this phase.
- No relaxed CSV parsing or fuzzy header matching.

---

## 3. Page Architecture

- Route remains `**/asn_new`**.
- Add tab UI on the same page:
  - **Single ASN**
  - **Bulk ASN Upload**
- Each tab has independent form state and submit action.
- Prevent cross-tab state contamination (switching tabs must not leak hidden-field values into submit payloads).
- Use separate form elements per tab plus an explicit submit-mode discriminator (`mode=single|bulk`) validated server-side.

---

## 4. UX Design — Single ASN Tab

### 4.1 Header fields

- `supplier_invoice_no`
- `supplier_invoice_date`
- `expected_delivery_date`
- `lr_no`
- `lr_date`
- `transporter_name`

### 4.2 Purchase Order selection

- Link-style typeahead flow (Frappe-like) with multi-selection chips.
- PO candidates limited to supplier-owned open POs.
- Selected POs become the allowed source for all manual rows.

### 4.3 Manual rows

Each row contains:

- `purchase_order` (Link-like; filtered to selected PO chips)
- `sr_no` (**mandatory**)
- `item_code` (Link-like; filtered to the selected row PO and resolved PO line scope)
- `uom` (auto-fill on item selection, editable)
- `qty` (mandatory)
- `rate` (auto-fill on item selection, editable)

### 4.4 Dependency behavior

- If row `purchase_order` changes:
  - clear `sr_no`, `item_code`, `uom`, `rate` immediately
  - force row re-selection under the new PO context

---

## 5. UX Design — Bulk ASN Upload Tab

### 5.1 Outcome

- One bulk upload can create **multiple ASNs** in one operation.
- Enforce **1:1 mapping** between ASN and `supplier_invoice_no`.

### 5.2 Strict bulk CSV schema

Required columns in exact order:

`supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,purchase_order,sr_no,item_code,qty,rate`

Bulk CSV intentionally does **not** include `uom`; UOM is derived from the resolved PO item.

### 5.3 Grouping and creation

- Group rows by `supplier_invoice_no`.
- Create one ASN per invoice group.
- Invoice-level consistency checks:
  - rows with same `supplier_invoice_no` must have identical values for:
    - `supplier_invoice_date`
    - `expected_delivery_date`
    - `lr_no`
    - `lr_date`
    - `transporter_name`
  - normalization rules before comparison:
    - trim surrounding whitespace
    - treat empty string and missing CSV cell as equivalent blank value
  - mismatch in any of the above fails the entire upload.

---

## 6. Validation and Mapping Rules

### 6.1 Shared rules (single + bulk)

- Authenticated supplier user required.
- PO must belong to supplier and be open.
  - Open PO means `docstatus = 1` and `status in ("To Receive", "To Receive and Bill")`.
- `sr_no` is **mandatory** and used as the primary PO line resolver.
- `item_code` must match resolved PO line.
- Quantity and rate validations:
  - `qty` must be strictly greater than 0.
  - `rate` must be greater than or equal to 0.
  - ASN row `qty` cannot exceed remaining receivable quantity for the resolved PO item.

### 6.1.1 Bulk-only row uniqueness rule

- In bulk mode, duplicate `purchase_order + sr_no` rows within the same `supplier_invoice_no` group are invalid.

### 6.2 Resolver priority

1. Resolve PO item by `purchase_order + sr_no`.
2. Validate that resolved PO item matches supplied `item_code`.
3. Use resolved PO item name as `purchase_order_item` in ASN item row.

No fallback to non-`sr_no` inference in this design.
If `purchase_order + sr_no` resolves to zero or multiple PO rows, fail with a row-specific validation error.

### 6.3 Failure mode

- **All-or-nothing** for each submit path:
  - single tab: one ASN fails => nothing created
  - bulk tab: any row/group fails => no ASNs created
- Error payloads must include row context:
  - row number (1-based manual row index; CSV uses source line numbers starting at 2)
  - invoice number (bulk)
  - field and message
- For cross-row invoice-group consistency failures:
  - emit one error per offending row in the group (not a single group-only error)
  - `field` is the specific inconsistent column name (for example `lr_date`)
  - `message` includes expected value and found value for that row

### 6.4 Request/response contract

- Request mode:
  - single form posts with `mode=single`
  - bulk form posts with `mode=bulk`
- Success:
  - single returns redirect to created ASN route
  - bulk re-renders page with inline success summary containing created ASN names and count
- Validation failure:
  - return HTTP 417 and re-render page with structured errors containing `row_number`, `invoice_no` (bulk), `field`, `message`
- Permission failure:
  - return HTTP 403
- Response format:
  - website form POST flow (HTML response), no JSON API in this phase

### 6.5 Throughput limits (hard limits)

- Reject uploads above 5,000 CSV data rows.
- Reject uploads above 500 invoice groups per submission.
- Limits are enforced in production validation and covered by tests.

---

## 7. Implementation Boundaries

Split responsibilities to keep current module maintainable:

- **UI composition layer** (`asn_new.html` + focused JS):
  - tabs
  - link-like controls
  - row interactions and dependencies
- **Request parsing layer** (`asn_new.py`):
  - normalize single/bulk payloads into shared row contract
- **Validation/resolution layer** (new helper module preferred):
  - supplier PO scope checks
  - PO line resolution via `sr_no`
  - row/group validation reporting
- **Creation layer**:
  - create+submit ASN(s) from validated groups

---

## 8. Error UX

- Single tab:
  - inline alert at top
  - row-labeled errors (`Manual row N: ...`)
- Bulk tab:
  - grouped errors by invoice and row
  - explicit “no ASNs created” summary on failure

---

## 9. Testing Strategy

- Unit tests for:
  - PO search scope (supplier + open only)
  - PO line resolve by `purchase_order + sr_no`
  - `item_code` mismatch detection against resolved line
  - bulk grouping by `supplier_invoice_no`
  - invoice metadata consistency per group
  - duplicate `purchase_order + sr_no` rows in the same invoice group are rejected
  - upload hard limits (row and invoice group caps) are enforced
- Page/controller tests for:
  - tab-specific submit behavior
  - all-or-nothing outcomes
  - error content includes row/invoice context
- Regression checks:
  - existing `/asn` listing and permission behavior remains unchanged
  - strict CSV header/order validation remains enforced for bulk CSV flow
  - Single tab remains manual-row only (no CSV upload path)

---

## 10. Accepted Decisions From Brainstorming

- Keep one route and use tabs (**Single ASN** + **Bulk ASN Upload**).
- Use Frappe-like link interactions for PO and row item selection.
- `uom` and `rate` auto-fill but remain editable.
- Changing row PO clears dependent item fields.
- `lr_no`, `lr_date`, `transporter_name` are **header-level** fields.
- `sr_no` is mandatory for row resolution.
- Bulk upload creates multiple ASNs and enforces 1 ASN per supplier invoice number.

