# ASN Branch-Wise Stock Cap Design

> **Superseded in part by [2026-08-03-per-branch-stock-cap-design.md](2026-08-03-per-branch-stock-cap-design.md).**
> The ceiling is no longer `Item.custom_max_stock`, a single number per item applied to every
> branch alike. It is now one `ASN Item Branch Cap` row per `(branch, item)` pair, and
> `Item.custom_max_stock` has been **retired** — `asn_module/patches/remove_item_max_stock_field.py`
> deletes the Custom Field on migrate. Do not create that field on any site.
>
> Everything else here still holds: Cap Warehouses per Branch, warn on ASN save, block on ASN and
> Purchase Receipt submit, redaction for users without `read` on `Item`, and the advisory
> (non-transactional) semantics. This document is kept as the record of the original design.

## Goal
Refuse an ASN submission, and a Purchase Receipt submission, when the stock it will land pushes an item above its permitted maximum for the destination branch. Warn at ASN draft save, block at submit.

Domain vocabulary for this feature is defined in [CONTEXT.md](../../../CONTEXT.md). Terms in Title Case below refer to that glossary.

## Confirmed Constraints
- Cap Warehouses are configured per Branch, not per ASN line and not per Purchase Order line.
- Branch comes from the Purchase Order header (`Purchase Order.branch`) and the Purchase Receipt header (`Purchase Receipt.branch`). Both exist as Accounting Dimension custom fields (`Link` -> `Branch`, `insert_after: dimension_col_break`), verified on production and replicated onto bench15 and bench16. See [Environment Prerequisites](#environment-prerequisites).
- `Item.custom_max_stock` is Maximum Stock, expressed in the item's stock UOM. `Item.safety_stock` is out of scope.
- ASN draft save must never be blocked. ASN submit and Purchase Receipt submit must be blocked.
- Every unconfigured path fails open, so rollout cannot break existing flows.
- Must remain installable and testable on stock Frappe/ERPNext v15 and v16, where neither `branch` nor `custom_max_stock` exists.

## Out of Scope
- `Item.safety_stock`. Deferred by explicit decision.
- Any schema change to `ASN`, `ASN Item`, `Item`, `Purchase Order`, or `Purchase Receipt`.
- Creating the `branch` fields. They are supplied by the Branch Accounting Dimension.
- Transactional guarantees. See [Concurrency](#concurrency).

## Data Model

### New DocType: `ASN Stock Cap Settings`
Not a Single. One document per Branch.

| Field | Type | Notes |
| --- | --- | --- |
| `branch` | Link -> Branch | `autoname: field:branch`, unique. The document name is the Branch. |
| `enabled` | Check | Default 1. Unchecked disables the Stock Cap for that Branch. |
| `warehouses` | Table -> `ASN Stock Cap Warehouse` | The Cap Warehouses. |

Controller validation:
- Reject a warehouse with `is_group = 1`. `Warehouse` is `is_tree: 1` and `Bin` rows exist only for leaves, so a group warehouse would compute On Hand as 0 forever and the cap would silently never fire.
- Reject a warehouse already listed under another Branch's settings, naming that Branch. A per-branch ceiling assumes each warehouse belongs to exactly one Branch.
- Reject duplicate warehouses within one document.

### New Child DocType: `ASN Stock Cap Warehouse`
Single field `warehouse` (Link -> Warehouse, reqd).

### Unchanged
`ASN`, `ASN Item`, `Item`, `Purchase Order`, and `Purchase Receipt` keep their current schemas.

## Units

`ASN Item.qty` and `ASN Item.received_qty` are in the Purchase Order line's **purchase UOM**, not stock UOM. [`handlers/purchase_receipt.py:105`](../../../asn_module/handlers/purchase_receipt.py) already establishes this: `pr_item.stock_qty = flt(asn_item.qty) * flt(pr_item.conversion_factor or 1)`.

`Bin.actual_qty` and `Item.custom_max_stock` are in stock UOM. Every ASN-sourced quantity is therefore multiplied by `Purchase Order Item.conversion_factor` before it enters any sum. Comparing raw ASN quantities against Bin quantities would make the cap silently inert for any item ordered in a pack UOM.

`Purchase Receipt Item.stock_qty` is already in stock UOM and needs no conversion.

## Resolution Chain

ASN path, per line:

```
ASN Item.purchase_order -> Purchase Order.branch
  -> ASN Stock Cap Settings (name = branch) -> enabled + Cap Warehouses
```

Purchase Receipt path, per document:

```
Purchase Receipt.branch
  -> ASN Stock Cap Settings (name = branch) -> enabled + Cap Warehouses
```

## Fail-Open Rules
Each skips the affected line silently. No warning, no block.

- `Purchase Order.branch` or `Purchase Receipt.branch` column absent on the site.
- `Item.custom_max_stock` column absent on the site.
- The source document has no `branch` value.
- No `ASN Stock Cap Settings` document exists for that Branch.
- Settings exist but `enabled` is 0, or the Cap Warehouses table is empty.
- `Item.custom_max_stock` is null or 0.
- No `Bin` row exists for an (item, warehouse) pair. `SUM` returns NULL, coalesced to 0.

Treating 0 as uncapped is deliberate. Frappe Float custom fields default to 0, so a stored 0 cannot be distinguished from never-configured.

## Evaluation Logic

New module `asn_module/stock_cap.py`, split into three parts so the decision logic is testable without stock fixtures.

### 1. `collect_lines(source) -> list[Line]`
Normalises a saved ASN, an unsaved ASN payload, a bulk-upload payload, or a Purchase Receipt into a common shape: `(branch, item_code, warehouse, stock_qty, row_idx)`. UOM conversion happens here, so nothing downstream deals in purchase UOM.

### 2. `fetch_cap_context(lines, exclude_asn_name=None) -> CapContext`
Runs every query and returns plain dicts. No decisions.

### 3. `evaluate(lines, context, consumed=None) -> list[Breach]`
Pure. No database, no `frappe` calls. Groups by `(branch, item_code)` and per group computes:

```
on_hand    = SUM(Bin.actual_qty)
             WHERE item_code = X AND warehouse IN cap_warehouses

in_transit = SUM(max(qty - received_qty, 0) * conversion_factor)
             over OTHER ASNs, docstatus = 1,
             status NOT IN ('Received', 'Closed'),
             item_code = X,
             joined to Purchase Order Item where
             COALESCE(poi.warehouse, po.set_warehouse) IN cap_warehouses

incoming   = SUM(stock_qty) of the source document's lines in the group

projected  = on_hand + in_transit + incoming + consumed.get((branch, item_code), 0)
breach     if projected > custom_max_stock
```

`consumed` carries Consumed Headroom for bulk upload and is empty elsewhere.

`Bin.ordered_qty` and `Bin.projected_qty` are deliberately unused: `ordered_qty` already covers the open Purchase Order the ASN ships against, so including it would double-count.

In Transit is filtered by warehouse rather than by the other ASN's branch, so it describes exactly the same warehouse set as On Hand.

### Breach
Carries `branch`, `item_code`, `row_idxs`, `on_hand`, `in_transit`, `incoming`, `projected`, `cap`, and a derived `allowed_qty`. No formatting is baked in.

### Boundary
Strictly greater. `projected == custom_max_stock` is allowed.

### Self-Exclusion
By `ASN.name` on the ASN path. Amended ASNs need no special case: the original sits at `docstatus = 2`, already excluded by the `docstatus = 1` filter.

### Query Cost
Six queries per evaluation regardless of line count, all batched with `IN` lists: branch map, settings plus Cap Warehouses, `Item.custom_max_stock`, `Purchase Order Item.conversion_factor`, Bin aggregate, In Transit aggregate.

`tabBin` carries its unique `(item_code, warehouse)` index and `ASN Item.item_code` is Link-indexed by Frappe, so both aggregates are index-driven and sargable.

## Concurrency

The evaluator reads without locking. Two ASNs for the same item submitted in overlapping requests both observe the same On Hand and In Transit figures, both pass, and together may breach the cap.

This is accepted. The Stock Cap is a business guardrail against bulk over-supply, not a hard invariant. The breach window is two submissions inside the same instant and the overshoot is bounded by one shipment. `SELECT ... FOR UPDATE` on Bin rows was rejected because it contends with ERPNext's own stock posting on the submit hot path, trading a narrow window for realistic deadlock risk.

**The cap is advisory, not transactional.** No downstream code may treat it as a guarantee that stock never exceeds Maximum Stock.

## Enforcement Surfaces

### Desk ASN controller (`asn.py`)
- `validate()` appends `self._warn_stock_cap()` after `_validate_po_qty()`. Raises a yellow-indicator `msgprint`. Never blocks; drafts always save.
- New `before_submit()` calls `self._validate_stock_cap()`, issuing one `frappe.throw` with all Breaches joined. Chosen over `on_submit` so nothing is written and no traceability transition is emitted before the block.

Desk message per Breach:

> Item {item_code} in branch {branch} (rows {idxs}): projected stock {projected} exceeds maximum {cap}. On hand {on_hand}, in transit {in_transit}, this ASN {incoming}.

### Purchase Receipt (`hooks.py`, `handlers/purchase_receipt.py`)
`doc_events["Purchase Receipt"]` already exists; a `before_submit` entry is added beside the current `on_submit`.

- Returns (`is_return = 1`) are skipped. Negative quantities reduce stock and can never breach a maximum.
- Each line contributes up to two entries: `stock_qty` into `warehouse`, and rejected qty into `rejected_warehouse`. Each counts only if that warehouse is a Cap Warehouse, matching what the stock ledger will actually post.
- `Purchase Receipt.asn` is passed as `exclude_asn_name`. Without it the source ASN still sits at `Submitted` with `received_qty` 0, so its quantity would be counted once as In Transit and again as the receipt's own quantity.

### Supplier portal (`asn_new_services.py`)
The portal inserts then submits, so the `before_submit` throw propagates. It is re-raised as a `PortalValidationError` and renders as a field-level error rather than a raw traceback.

New whitelisted `get_stock_cap_preview(items, asn_name=None)`. Each entry carries `purchase_order`, `item_code`, and `qty`, so a payload spanning several Purchase Orders is handled by the same grouping as a saved document. Access is gated per Purchase Order by the existing `_get_accessible_purchase_order`.

> **Withdrawn.** `get_stock_cap_preview` was never built out as a client-facing feature and was
> removed in `3bf9064` (`refactor: drop the unused stock cap preview endpoint and package facade`)
> along with the rest of the unused preview call chain. No whitelisted preview endpoint exists on
> this branch. The portal's only stock-cap-facing behaviour is the block on submit described just
> above.

**Disclosure:** portal responses and portal-facing messages expose Allowed Qty and a breach flag only. On Hand, In Transit Qty, and Maximum Stock are inventory levels and purchasing ceilings, and are never sent to a supplier. This applies to the block message and the save-time warning as well as the preview. Desk users receive the full Breach detail.

### Desk bulk upload (`bulk_upload.py` -> `create_bulk_asns_for_supplier`)
The cap is evaluated during the **validation phase**, across all parsed payloads, before the insert loop begins. Breaches feed the existing `errors` list and raise one `PortalValidationError` carrying "No ASNs created due to validation failures."

This preserves the function's existing all-or-nothing contract. The insert loop at [`asn_new_services.py:613`](../../../asn_module/templates/pages/asn_new_services.py) is unguarded and runs after the error check, so wrapping submission would both break that contract and leave already-submitted ASNs behind a raw exception.

Consumed Headroom is carried across payload groups keyed by `(branch, item_code)`, mirroring how `running_remaining` at [`asn_new_services.py:592`](../../../asn_module/templates/pages/asn_new_services.py) already prevents several CSV groups from each passing the PO quantity check individually.

## Testing

E2E first, per project conventions.

### Cypress (`tests/e2e/specs/`)
- Under-cap ASN submits successfully.
- Over-cap ASN shows the block message and stays in draft.
- Over-cap draft saves and shows a visible warning.
- Portal block message shows Allowed Qty and no stock figures.

### Unit, pure `evaluate` (`asn_module/tests/test_stock_cap.py`)
Hand-built `CapContext`, no fixtures:

- No cap set on the item.
- Under cap.
- Exactly at cap, allowed.
- Breached by the source document alone.
- Breached only once In Transit is counted.
- Breached only once Consumed Headroom is applied.
- Warehouse outside the Cap Warehouses is ignored.
- Multiple lines for the same item summed into one group.
- Rejected quantity counted when its warehouse is a Cap Warehouse, ignored otherwise.
- Return receipts skipped.

### Unit, `collect_lines`
- Purchase UOM converted via `conversion_factor`.
- `conversion_factor` of 0 or null treated as 1.
- Purchase Receipt lines pass `stock_qty` through unconverted.

### Integration, `fetch_cap_context`
- In Transit excludes Received, Closed, and cancelled ASNs.
- `exclude_asn_name` excludes the named ASN.
- Settings disabled, and no settings document for the Branch.
- Source document without a branch value.
- `has_column` guards for `branch` and `custom_max_stock`.
- Missing Bin rows coalesce to 0.

### Integration (`test_asn.py`, `handlers/tests/test_purchase_receipt.py`)
- ASN save warns but succeeds.
- ASN submit throws.
- Purchase Receipt submit throws, and does not double-count its own ASN.
- Portal path surfaces a field-level error with no stock figures.
- Bulk upload creates nothing when any group breaches.

### Settings validation (`asn_module/tests/test_stock_cap_settings.py`)
- Group warehouse rejected.
- Warehouse already claimed by another Branch rejected.
- Duplicate warehouse within one document rejected.

### Property tests (`property_tests/test_stock_cap_properties.py`)
- Projected Stock is monotonic non-decreasing in declared quantity.
- Breach holds if and only if `projected > cap`.
- `allowed_qty` is the largest quantity that does not breach.

### Coverage
Target 96% per project conventions. The pure `evaluate` function makes the branch matrix reachable without stock ledger fixtures.

## Compatibility
The evaluator guards with `frappe.db.has_column` for `Purchase Order.branch`, `Purchase Receipt.branch`, and `Item.custom_max_stock`, and skips entirely when any is absent. The app installs and the full suite passes on a stock v15 or v16 bench without the Branch accounting dimension configured.

## Environment Prerequisites

Verified against production (`trikayacoatings.frappe.cloud`) on 2026-07-28 and replicated onto both local benches.

| Field | Production | bench15 | bench16 |
| --- | --- | --- | --- |
| `Purchase Order.branch` | present | present | present |
| `Purchase Order Item.branch` | present | present | present |
| `Purchase Receipt.branch` | present | created 2026-07-28 | created 2026-07-28 |
| `Purchase Receipt Item.branch` | present | created 2026-07-28 | created 2026-07-28 |
| `Item.custom_max_stock` | ~~absent~~ retired | ~~present~~ removed | ~~present~~ removed |

All `branch` fields come from a single `Accounting Dimension` record with `document_type = Branch`, which stamps `branch` (`Link` -> `Branch`, `insert_after: dimension_col_break`) onto every doctype in ERPNext's `accounting_dimension_doctypes` hook.

> **Retired — do not create this field.** `Item.custom_max_stock` was never created on production, and
> the per-branch redesign removed it entirely: `asn_module/patches/remove_item_max_stock_field.py`
> deletes the Custom Field on migrate. The ceiling now lives in `ASN Item Branch Cap`, one row per
> `(branch, item)`. A site with no cap rows reads no ceiling and fails open silently, exactly as
> described here — but the guard is `table_exists("ASN Item Branch Cap")`, not a `has_column` check
> on `Item`. The original instruction to replicate a `Float` field after `safety_stock` no longer
> applies and would be undone by the next migrate.

**Creating the dimension requires a synchronous call.** `AccountingDimension.on_update` enqueues `make_dimension_in_accounting_doctypes` to the `long` queue unless `frappe.in_test` is set. Inserting the record with no worker running leaves every field uncreated. Any CI or ephemeral-site fixture that sets up the dimension must call the function directly or run under `frappe.in_test`.

## Known Limitations
- The cap is advisory under concurrency. See [Concurrency](#concurrency).
- A multi-branch ASN can be created on the desk but can never be receipted: [`handlers/purchase_receipt.py:63`](../../../asn_module/handlers/purchase_receipt.py) throws "ASN can reference only one Purchase Order". Per-branch grouping is retained because it is free and defensively correct, but no E2E case covers it. This is pre-existing behaviour, not introduced here.
- Stock movements outside the ASN and Purchase Receipt paths (Stock Entry, Stock Reconciliation, transfers between Cap Warehouses) are unguarded and can carry an item above Maximum Stock.
