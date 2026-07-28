# ASN Branch-Wise Stock Cap Design

## Goal
Block submission of an ASN when the stock it will land pushes an item above its configured maximum for the destination branch. Warn at draft save, block at submit.

## Confirmed Constraints
- Warehouses are configured per branch, not per ASN line and not per Purchase Order line.
- The branch comes from the Purchase Order header (`Purchase Order.branch`).
- `Item.custom_max_stock` is the cap. `Item.safety_stock` is out of scope for this change.
- Draft save must never be blocked. Submit must be blocked.
- Every unconfigured path fails open, so rollout cannot break existing ASN flows.
- Must remain installable and testable on stock Frappe/ERPNext v15 and v16, where `Purchase Order.branch` does not exist.

## Out of Scope
- `Item.safety_stock`. No warning, no block, no display. Deferred by explicit decision.
- Any schema change to `ASN` or `ASN Item`.
- Any schema change to `Item`. `custom_max_stock` is read as an existing site custom field.
- Creating the `Purchase Order.branch` field. It is assumed to exist on the target site.

## Data Model

### New DocType: `ASN Stock Cap Settings`
Not a Single. One document per branch.

| Field | Type | Notes |
| --- | --- | --- |
| `branch` | Link -> Branch | `autoname: field:branch`, unique. The document name is the branch. |
| `enabled` | Check | Default 1. Unchecked disables the cap for that branch. |
| `warehouses` | Table -> `ASN Stock Cap Warehouse` | The warehouse set the cap sums over. |

### New Child DocType: `ASN Stock Cap Warehouse`
Single field `warehouse` (Link -> Warehouse, reqd). The parent controller rejects duplicate warehouses within one settings document.

### Unchanged
`ASN`, `ASN Item`, and `Item` keep their current schemas.

## Resolution Chain
Per ASN line:

```
ASN Item.purchase_order
  -> Purchase Order.branch
    -> ASN Stock Cap Settings (name = branch)
      -> enabled flag + warehouse list
```

## Fail-Open Rules
Each of these skips the affected line silently. No warning, no block.

- `Purchase Order.branch` column does not exist on the site.
- The Purchase Order has no `branch` value.
- No `ASN Stock Cap Settings` document exists for that branch.
- Settings exist but `enabled` is 0.
- Settings exist and are enabled but the warehouse table is empty.
- `Item.custom_max_stock` is null or 0.

Treating 0 as "uncapped" is deliberate. Frappe Float custom fields default to 0, so a stored 0 cannot be reliably distinguished from "never configured".

## Evaluation Logic

New module `asn_module/stock_cap.py`. Pure evaluator. It never throws and never prints.

```
evaluate_asn_stock_cap(doc) -> list[CapBreach]
```

Lines are grouped by `(branch, item_code)`. Per group:

```
on_hand    = SUM(Bin.actual_qty)
             WHERE item_code = X AND warehouse IN branch_warehouses

in_transit = SUM(max(qty - received_qty, 0))
             over OTHER ASNs, docstatus = 1,
             status NOT IN ('Received', 'Closed'),
             item_code = X,
             joined to Purchase Order Item where
             COALESCE(poi.warehouse, po.set_warehouse) IN branch_warehouses

this_asn   = SUM(qty) of this ASN's lines in the group

projected  = on_hand + in_transit + this_asn
breach     if projected > custom_max_stock
```

`Bin.ordered_qty` and `Bin.projected_qty` are deliberately not used. `ordered_qty` already covers the open Purchase Order this ASN ships against, so including it would double-count the ASN quantity.

The in-transit figure is filtered by warehouse rather than by the other ASN's branch. This keeps it describing exactly the same warehouse set as the on-hand figure.

### CapBreach
Carries `branch`, `item_code`, `row_idxs`, `on_hand`, `in_transit`, `this_asn`, `projected`, `cap`. No formatting is baked in, so the same value serves both the user message and the preview API.

### Boundary
Strictly greater. `projected == custom_max_stock` is allowed.

### Self-Exclusion
By `ASN.name`. Amended ASNs need no special case: the original sits at `docstatus = 2` and is already excluded by the `docstatus = 1` filter.

### Query Cost
Five queries per evaluation regardless of line count, all batched with `IN` lists:

1. Purchase Order -> branch map
2. Settings plus warehouse rows
3. `Item.custom_max_stock`
4. Bin aggregate
5. In-transit aggregate

`tabBin` carries its unique `(item_code, warehouse)` index and `ASN Item.item_code` is Link-indexed by Frappe, so both aggregates are index-driven and sargable.

## Enforcement Surfaces

### Desk controller (`asn.py`)
- `validate()` appends `self._warn_stock_cap()` after `_validate_po_qty()`. It calls the evaluator and raises a yellow-indicator `msgprint` listing each breach. It never blocks. Drafts always save.
- New `before_submit()` calls `self._validate_stock_cap()`, which issues one `frappe.throw` with all breaches joined. `before_submit` is chosen over `on_submit` so nothing is written and no traceability transition is emitted before the block.

Message per breach:

> Item {item_code} in branch {branch} (rows {idxs}): projected stock {projected} exceeds maximum {cap}. On hand {on_hand}, in transit {in_transit}, this ASN {this_asn}.

All user-visible strings are wrapped in `_()`.

### Supplier portal (`asn_new_services.py`)
The portal inserts then submits (`asn.insert()`, `asn.submit()`), so the `before_submit` throw propagates. The `submit()` call is wrapped so the breach is re-raised as a `PortalValidationError` and renders as a field-level portal error rather than a raw traceback.

New whitelisted `get_stock_cap_preview(items, asn_name=None)` lets the portal show headroom before the user commits. Each entry in `items` carries `purchase_order`, `item_code`, and `qty`, so a payload spanning several Purchase Orders (and therefore several branches) is handled by the same grouping as a saved document. `asn_name` is passed when editing an existing draft so it is excluded from the in-transit figure.

### Desk bulk upload (`bulk_upload.py` -> `create_bulk_asns_for_supplier`)
The function already aggregates per-invoice-group failures into `errors` and raises a single `PortalValidationError`. The submit call moves inside that same try/except, so one breaching group reports its own error while the remaining groups still create.

## Testing

E2E first, per project conventions.

### Cypress (`tests/e2e/specs/`)
- Under-cap ASN submits successfully.
- Over-cap ASN shows the block message and stays in draft.
- Over-cap draft saves and shows a visible warning.

### Unit, evaluator (`asn_module/tests/test_stock_cap.py`)
Plain data, no document lifecycle:

- No cap set on the item.
- Under cap.
- Exactly at cap, allowed.
- Breached by this ASN alone.
- Breached only once in-transit is counted.
- In-transit excludes Received, Closed, and cancelled ASNs.
- Warehouse outside the branch list is ignored.
- Settings disabled.
- No settings document for the branch.
- Purchase Order without a branch value.
- `has_column` guard when `Purchase Order.branch` is absent.
- Multi-branch ASN evaluated per branch.
- Multiple lines for the same item summed into one group.

### Integration (`test_asn.py`)
- Save warns but succeeds.
- Submit throws.
- Portal path surfaces a field-level error.
- Bulk upload partial success: breaching group fails, others create.

### Property tests (`property_tests/test_stock_cap_properties.py`)
- Projected quantity is monotonic non-decreasing in ASN quantity.
- Breach holds if and only if `projected > cap`.

### Coverage
Target 96% per project conventions. `stock_cap.py` being a pure function module makes the branch matrix above reachable without stock ledger fixtures.

## Compatibility
The evaluator guards with `frappe.db.has_column("Purchase Order", "branch")` and skips entirely when the column is absent. The app installs and the full suite passes on a stock v15 or v16 bench without the Branch accounting dimension configured.
