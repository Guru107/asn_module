# Barcode Flow Wiki (User Guide)

> Applies to the current relational `Barcode Flow *` model.
> Planned one-screen hard-cut redesign is documented in `docs/superpowers/specs/2026-04-22-barcode-process-flow-one-screen-hard-cut-design.md`.

This page explains, from a System Manager/operator perspective, how to configure a full end-to-end barcode-driven process using one real example.

This is for the `Barcode Flow *` doctypes in this app (not ERPNext native `Workflow`).

## Example Use Case

You want this inbound process:

1. Supplier ASN barcode is scanned at security gate.
2. System creates **Gate Pass (Gate In)**.
3. Next scan creates **Purchase Receipt**.
4. From Purchase Receipt, system exposes two paths:
   - **Purchase Invoice** path for Accounts.
   - **Stock Transfer Entry** path for Store (only when inspection is required).
5. Optional dispatch path creates **Gate Pass (Gate Out)**.

### Flow Map

`ASN Barcode -> Gate Pass (Gate In) -> Purchase Receipt -> (Purchase Invoice + Stock Transfer Entry)`

Optional:

`Purchase Receipt -> Gate Pass (Gate Out)`

## Before You Start

1. Login as a role with permission to manage these doctypes (typically `System Manager`).
2. Confirm required doctypes/actions exist:
   - `Barcode Flow Definition`
   - `Barcode Flow Node`
   - `Barcode Flow Condition`
   - `Barcode Flow Field Map`
   - `Barcode Flow Action Binding`
   - `Barcode Flow Transition`
   - `QR Action Definition`
3. For non-standard documents (example: custom `Gate Pass`, direct Stock Entry from PR), ensure your app already has handler methods.

Note:
- Built-in actions include `create_purchase_receipt`, `create_purchase_invoice`, `create_stock_transfer` (from Quality Inspection), etc.
- If you need `Purchase Receipt -> Stock Entry` directly, create a custom `QR Action Definition` and custom handler.

## Step 1: Define Actions (`QR Action Definition`)

Create/verify action rows first.

Minimum rows for this use case:

1. `create_gate_pass_in` (custom)
   - `source_doctype`: `ASN`
   - `handler_method`: your custom gate-in handler
   - `allowed_roles`: roles that can scan at gate
2. `create_purchase_receipt_from_gate_pass` (custom or your chosen implementation)
   - `source_doctype`: `Gate Pass`
   - `handler_method`: creates PR from gate-pass context
3. `create_purchase_invoice` (existing or custom)
   - `source_doctype`: `Purchase Receipt`
4. `create_stock_transfer_from_pr` (custom if direct-from-PR is needed)
   - `source_doctype`: `Purchase Receipt`
5. Optional `create_gate_pass_out` (custom)
   - `source_doctype`: `Purchase Receipt` or your outbound source doctype

## Step 2: Create Flow Definition and Scope

Create one `Barcode Flow Definition`:

- `flow_name`: `Inbound::GateIn::PR::InvoiceAndTransfer`
- `is_active`: checked
- `description`: short business description

Add scope row inside `scopes` child table:

- `scope_key`: `default-inbound`
- `priority`: `100`
- `is_default`: checked
- `source_doctype`: `ASN`
- Optional filters: `company`, `warehouse`, `supplier_type` (use these when you need context-specific routing)

## Step 3: Create Nodes

Create `Barcode Flow Node` records with `flow` linked to your definition:

1. `scan_asn` (`Start`)
2. `gate_in_done` (`State`)
3. `pr_draft` (`State`)
4. `invoice_ready` (`End`)
5. `transfer_ready` (`End`)
6. Optional `gate_out_done` (`End`)

## Step 4: Create Field Maps

Create `Barcode Flow Field Map` rows for mapping transitions:

1. `gatein-to-pr` (if mapping mode is used for PR creation)
2. `pr-to-pi` (if mapping mode is used for PI creation)
3. `pr-to-transfer` (if mapping mode is used for Stock Entry)

For each row:

- `mapping_type`: `source` or `constant`
- `source_field_path`: source document field path (for `source` mode)
- `target_field_path`: target document field path
- `constant_value`: only for `constant` mode

## Step 5: Add Rules (Conditions)

Create `Barcode Flow Condition` rows for route control.

### Item-level rule (day-one requirement)

Example: “any item requires inspection”

- `condition_key`: `any-item-needs-inspection`
- `scope`: `items_any`
- `field_path`: `inspection_required_before_purchase`
- `operator`: `=`
- `value`: `1`

### Aggregate rule example

Example: total line count must be at least 1

- `condition_key`: `at-least-one-line`
- `scope`: `items_aggregate`
- `aggregate_fn`: `count`
- `field_path`: `item_code`
- `operator`: `>=`
- `value`: `1`

## Step 6: Create Action Bindings

Create `Barcode Flow Action Binding` rows for custom handler execution.

Example bindings:

1. `bind-gate-in`
   - `trigger_event`: `custom_handler`
   - `action`: `create_gate_pass_in`
   - `custom_handler`: your gate-in method
2. `bind-pr-create`
   - `trigger_event`: `custom_handler`
   - `action`: `create_purchase_receipt_from_gate_pass`
3. `bind-pr-to-transfer`
   - `trigger_event`: `custom_handler`
   - `action`: `create_stock_transfer_from_pr`
4. Optional `bind-gate-out`
   - `trigger_event`: `custom_handler`
   - `action`: `create_gate_pass_out`

## Step 7: Create Transitions

Now create `Barcode Flow Transition` rows.

Recommended setup:

1. `asn-to-gatein`
   - `source_node`: `scan_asn`
   - `target_node`: `gate_in_done`
   - `action`: `create_gate_pass_in`
   - `binding_mode`: `custom_handler`
   - `action_binding`: `bind-gate-in`
   - `generation_mode`: `hybrid` (recommended)

2. `gatein-to-pr`
   - `source_node`: `gate_in_done`
   - `target_node`: `pr_draft`
   - `action`: `create_purchase_receipt_from_gate_pass`
   - `binding_mode`: `custom_handler` (or `mapping`/`both` as designed)
   - `action_binding`: `bind-pr-create`
   - `generation_mode`: `hybrid`

3. `pr-to-pi`
   - `source_node`: `pr_draft`
   - `target_node`: `invoice_ready`
   - `action`: `create_purchase_invoice`
   - `binding_mode`: `custom_handler` or `both`
   - `generation_mode`: `immediate` or `hybrid`

4. `pr-to-transfer`
   - `source_node`: `pr_draft`
   - `target_node`: `transfer_ready`
   - `action`: `create_stock_transfer_from_pr`
   - `binding_mode`: `custom_handler` or `both`
   - `action_binding`: `bind-pr-to-transfer`
   - `condition`: `any-item-needs-inspection`
   - `generation_mode`: `hybrid`

5. Optional `pr-to-gateout`
   - `source_node`: `pr_draft`
   - `target_node`: `gate_out_done`
   - `action`: `create_gate_pass_out`
   - `binding_mode`: `custom_handler`

## Step 8: Test the End-to-End Flow

Run one controlled test document through the scanner sequence.

### Test Case A: Item requires inspection

1. Scan ASN barcode -> Gate In document should be created.
2. Scan next barcode -> Purchase Receipt should be created.
3. At PR stage, you should see paths for:
   - Purchase Invoice
   - Stock Transfer (because condition matched)

### Test Case B: No item requires inspection

1. Repeat with all items having inspection flag off.
2. Stock Transfer path should not be produced for this route.
3. Purchase Invoice path should still work.

## Step 9: Verify Auditability

Check:

1. `Scan Log`
   - `barcode_flow_definition`
   - `barcode_flow_transition`
   - `scope_resolution_key`
2. Generated target documents exist and are linked correctly.
3. No ambiguity errors during scan.

## Common Mistakes

1. **Wrong source doctype in action definition**
   - Scans fail because action expects a different source document type.
2. **Cross-flow linking**
   - Link fields only allow records from the same flow; setup must stay flow-consistent.
3. **Missing binding contract**
   - `custom_handler` modes require valid action binding and handler method.
4. **Overly narrow scope**
   - If scope filters are too tight, no flow matches at runtime.

## Variant: Direct ASN -> Purchase Receipt (No Gate Pass Module)

If `Gate Pass` is not installed, configure a simpler route:

`ASN Barcode -> Purchase Receipt -> (Purchase Invoice + other next-step transitions)`

For this variant:

1. Use `source_doctype=ASN` in scope.
2. Use `create_purchase_receipt` action.
3. Remove Gate Pass nodes/transitions.
4. Keep downstream PR transitions as needed.

---

If you want, this wiki can be cloned into your internal SOP format with role-based sections (Security, Store, Accounts) and a go-live checklist page.
