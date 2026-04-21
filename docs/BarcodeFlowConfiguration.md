# Barcode Flow Configuration Guide

This runbook is for System Managers/operators configuring `Barcode Flow Definition` so barcode scans route to the correct document actions without code changes.

## Scope and Trade-offs

- This guide favors explicit, strict configuration over permissive fallback behavior.
- Trade-off: stricter validation blocks bad config early, but setup requires careful key management (`scope_key`, `transition_key`, `map_key`, `binding_key`).
- Runtime matching is deterministic and fails on ambiguity.
- Trade-off: no best-effort routing means safer operations, but misconfigured overlaps stop scans until fixed.

## Prerequisites

1. `QR Action Registry` includes every `action_key` used in transitions.
2. Operators have required roles for each action in `QR Action Registry`.
3. Source documents include context used by scope matching (`source_doctype`, `company`, `warehouse`, `supplier_type`).

## Key DocTypes and Required Fields

### Barcode Flow Definition (parent)

Required:
- `flow_name`

Operational fields:
- `is_active`
- Child tables: `scopes`, `nodes`, `transitions`, `conditions`, `field_maps`, `action_bindings`

### Barcode Flow Scope (child table: `scopes`)

Required:
- `scope_key`
- `priority`
- `source_doctype`

Routing fields:
- `company`
- `warehouse`
- `supplier_type`
- `is_default` (only one default scope per flow)

### Barcode Flow Node (child table: `nodes`)

Required:
- `node_key`
- `label`
- `node_type` (`Start`, `State`, `End`)

### Barcode Flow Transition (child table: `transitions`)

Required:
- `transition_key`
- `generation_mode` (`immediate`, `runtime`, `hybrid`)
- `source_node_key`
- `target_node_key`
- `action_key`
- `binding_mode` (`mapping`, `custom_handler`, `both`)

Conditionally required:
- `target_doctype` when `binding_mode` is `mapping` or `both`
- `binding_key` when `binding_mode` is `custom_handler` or `both`

Optional references:
- `condition_key`
- `field_map_key`
- `priority`

### Barcode Flow Condition (child table: `conditions`)

Required:
- `condition_key`
- `scope` (`header`, `items_any`, `items_all`, `items_aggregate`)
- `field_path`
- `operator`

Conditionally required:
- `aggregate_fn` when `scope=items_aggregate`
- `value` unless operator is `exists` or `is_set`

### Barcode Flow Field Map (child table: `field_maps`)

Required:
- `map_key`
- `mapping_type` (`source`, `constant`)
- `target_field_path`

Conditionally required:
- `source_field_path` when `mapping_type=source`
- `constant_value` when `mapping_type=constant`

### Barcode Flow Action Binding (child table: `action_bindings`)

Required:
- `binding_key`
- `trigger_event` (`On Enter Node`, `On Exit Node`, `On Transition`, `custom_handler`)
- `action_key`

Conditionally required:
- `custom_handler` when `trigger_event=custom_handler`
- `target_node_key` when trigger is `On Enter Node` or `On Exit Node`
- `target_transition_key` when trigger is `On Transition`

## Example A: ASN -> Gate-like Step (Gate In simulation) -> Purchase Receipt

Use this when one warehouse requires a gate step before receipt creation.

### Flow A1: ASN to Gate In simulation

`Barcode Flow Definition`:
- `flow_name`: `Inbound::GateIn::ASN`
- `is_active`: checked

`scopes` row:
- `scope_key`: `gate-like-scope`
- `source_doctype`: `ASN`
- `company`: `Your Company`
- `warehouse`: `Main Stores - YC`
- `priority`: `300`
- `is_default`: checked

`nodes` rows:
- `asn_scan` (`Start`)
- `gate_in_simulated` (`State`)

`action_bindings` row:
- `binding_key`: `binding-asn-gate-in`
- `trigger_event`: `custom_handler`
- `action_key`: `asn_gate_in_simulation`
- `custom_handler`: `your_app.handlers.gate_in_simulation.handle`

`transitions` row:
- `transition_key`: `asn-to-gate-in`
- `source_node_key`: `asn_scan`
- `target_node_key`: `gate_in_simulated`
- `action_key`: `asn_gate_in_simulation`
- `generation_mode`: `runtime`
- `binding_mode`: `custom_handler`
- `binding_key`: `binding-asn-gate-in`
- `priority`: `200`

### Flow A2: Gate In simulation to Purchase Receipt

Use a second flow with `source_doctype` equal to the gate-step document doctype returned by your handler (for example `ToDo` in simulation).

`Barcode Flow Definition`:
- `flow_name`: `Inbound::GateInToPR`

`scopes` row:
- `scope_key`: `gate-step-source`
- `source_doctype`: `ToDo`
- `priority`: `300`

`nodes` rows:
- `gate_in_done` (`Start`)
- `pr_draft` (`End`)

`field_maps` rows (example):
- `map_key`: `gate_to_pr_supplier`, `mapping_type`: `source`, `source_field_path`: `reference_name`, `target_field_path`: `supplier`
- `map_key`: `gate_to_pr_wh`, `mapping_type`: `constant`, `constant_value`: `Main Stores - YC`, `target_field_path`: `set_warehouse`

`transitions` row:
- `transition_key`: `gate-in-to-pr`
- `source_node_key`: `gate_in_done`
- `target_node_key`: `pr_draft`
- `action_key`: `create_purchase_receipt`
- `generation_mode`: `hybrid`
- `binding_mode`: `mapping`
- `field_map_key`: `gate_to_pr_supplier` (or use hydrated map rows)
- `target_doctype`: `Purchase Receipt`

## Example B: ASN -> Purchase Receipt (Direct, no gate)

Use this where gate handling is not applicable.

`Barcode Flow Definition`:
- `flow_name`: `Inbound::DirectPR::ASN`

`scopes` row:
- `scope_key`: `direct-pr-scope`
- `source_doctype`: `ASN`
- `company`: `Your Company`
- `warehouse`: `Secondary Stores - YC`
- `priority`: `200`
- `is_default`: checked

`nodes` rows:
- `asn_scan` (`Start`)
- `pr_draft` (`End`)

`transitions` row:
- `transition_key`: `asn-to-pr-direct`
- `source_node_key`: `asn_scan`
- `target_node_key`: `pr_draft`
- `action_key`: `create_purchase_receipt`
- `generation_mode`: `hybrid`
- `binding_mode`: `mapping`
- `target_doctype`: `Purchase Receipt`

Recommended condition example (`conditions` + `condition_key`):
- `condition_key`: `asn-submitted`
- `scope`: `header`
- `field_path`: `docstatus`
- `operator`: `=`
- `value`: `1`

## Example C: Dispatch/Outbound -> Gate Out-like path -> Mark dispatched

Use this when outbound requires gate-out verification before final dispatch marking.

### Option 1 (recommended): two explicit transitions with separate actions

1. Outbound source document scan creates/opens gate-out step using `custom_handler`.
2. Gate-out document scan triggers `mark_dispatched` action (custom handler or mapping) to set final dispatched state.

`Flow C1` scope example:
- `source_doctype`: `Subcontracting Order`
- `scope_key`: `outbound-gate-out`
- `action_key` on transition: `create_subcontracting_dispatch`
- `binding_mode`: `custom_handler`

`Flow C2` scope example:
- `source_doctype`: `Delivery Note` (or your gate out doctype)
- `scope_key`: `outbound-mark-dispatched`
- `action_key` on transition: `mark_dispatched`
- `binding_mode`: `custom_handler` or `both`

Trade-off:
- Clear operational checkpoints and auditability, but one extra scan step.

### Option 2: single custom handler transition

Single transition from outbound source executes gate-out logic and dispatched marking in one handler.

Trade-off:
- Faster for operators, but less granular audit trail and less flexible exception handling.

## Troubleshooting

### 1) No matching flow

Typical message:
- `No active barcode flow matches context: {...}`

Causes:
- No active `Barcode Flow Definition` with matching `scopes`
- `source_doctype` mismatch
- Scope filters (`company`, `warehouse`, `supplier_type`) too restrictive

Fix:
1. Verify the scanned source document fields used by routing context.
2. Check scope filters and `is_active/enabled` flags.
3. Add a default scope (`is_default=1`) where appropriate.

### 2) Ambiguous flow or transition

Typical messages:
- `Ambiguous barcode flow resolution for context {...}. Matching scopes: ...`
- `Ambiguous barcode transition resolution in flow '...'. Matching transitions: ...`

Causes:
- Multiple scopes tie on specificity/priority/default
- Multiple transitions match same `action_key` at same effective priority/mode

Fix:
1. Make scopes mutually exclusive by context filters.
2. Adjust scope `priority` and ensure only one default candidate.
3. Make transition matching unique per action path (or adjust transition `priority`).

### 3) Missing binding key or field map key

Typical messages:
- `Transition <key> references unknown binding key: <binding_key>`
- `Transition <key> references unknown field map key: <map_key>`
- `Unknown binding key on transition: <binding_key>`
- `Unknown field map key on transition: <map_key>`

Causes:
- `binding_key` or `field_map_key` points to nonexistent child rows
- Flow definition context not supplied for key resolution in runtime

Fix:
1. Ensure referenced `binding_key` exists in `action_bindings`.
2. Ensure referenced `field_map_key` exists in `field_maps`.
3. Re-save flow after edits to trigger definition-level validation.

## Operator Verification Checklist

1. Scan a known code for each configured transition and confirm `Scan Log` is `Success`.
2. Confirm `Scan Log` fields are populated: `barcode_flow_definition`, `barcode_flow_transition`, `scope_resolution_key`.
3. Confirm generated/opened target document is expected doctype and state.
4. For `hybrid`/`immediate`, verify child scan codes are generated for the resulting target document.
