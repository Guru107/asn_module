# Barcode Flow Configuration Guide

This runbook is for System Managers and operators configuring barcode flows in the current relational model. The primary authoring surface is now flow-scoped linked records, not legacy `*_key` transition wiring.

## Scope and Trade-offs

- Configuration is strict and link-native. Invalid cross-flow references are rejected at save time instead of being tolerated until runtime.
- Trade-off: setup is more explicit, but failures move earlier and are easier to diagnose.
- Runtime transition matching is deterministic and flow-scoped. Ambiguous or underspecified routing fails fast.
- Trade-off: there is no broad fallback match when source node state is missing.
- Referenced records are delete-protected.
- Trade-off: cleanup requires detaching references first, but accidental graph corruption is blocked.

## Primary Records

### Barcode Flow Definition

Owns:
- `flow_name`
- `is_active`
- child table `scopes`

It does not own nodes, conditions, field maps, bindings, or transitions as child tables anymore. Those are standalone records linked back to the flow definition through their `flow` link field.

### Barcode Flow Scope

Still authored inside `Barcode Flow Definition.scopes`.

Required:
- `scope_key`
- `priority`
- `source_doctype`

Optional match fields:
- `company`
- `warehouse`
- `supplier_type`
- `is_default`

Runtime picks the winning scope by:
1. highest specificity
2. highest priority
3. single default scope

If that still leaves more than one candidate, resolution fails as ambiguous.

### Standalone Relational Records

These are created as separate documents and must all point to the same `flow`:
- `Barcode Flow Node`
- `Barcode Flow Condition`
- `Barcode Flow Field Map`
- `Barcode Flow Action Binding`
- `Barcode Flow Transition`

`QR Action Definition` is also part of the operational graph, but it is global and not flow-owned.

## Authoring Order

Use this order. It matches current validation, Desk link pickers, and runtime expectations.

### 1. Create `Barcode Flow Definition` and scopes

Create the flow record first, then add the `scopes` rows that decide when the flow is eligible.

Minimum:
- `flow_name`
- one active scope with `source_doctype`

### 2. Create Nodes, Conditions, Field Maps, and QR Action Definitions

Create standalone docs next:

- `Barcode Flow Node`
  - unique within flow by `(flow, node_key)`
- `Barcode Flow Condition`
  - unique within flow by `(flow, condition_key)`
- `Barcode Flow Field Map`
  - unique within flow by `(flow, map_key)`
- `QR Action Definition`
  - global source of truth for action resolution at dispatch/runtime

Important:
- `QR Action Definition` is the primary action source. Do not author flows assuming a registry-only fallback.
- Every node, condition, and field map used by a transition must belong to the same flow as that transition.

### 3. Create custom-handler bindings

Create `Barcode Flow Action Binding` records for any custom-handler execution path before transitions that reference them.

For `trigger_event=custom_handler`:
- `custom_handler` is required
- `target_node` must be empty
- `target_transition` must be empty

For event bindings:
- `On Enter Node` and `On Exit Node` require `target_node`
- `On Transition` requires `target_transition`

All node and transition targets must belong to the same flow as the binding.

### 4. Create transitions using flow-scoped link pickers

Create `Barcode Flow Transition` records only after the linked relational records already exist.

Desk link pickers are flow-scoped:
- `source_node`, `target_node` -> `Barcode Flow Node` in current `flow`
- `condition` -> `Barcode Flow Condition` in current `flow`
- `field_map` -> `Barcode Flow Field Map` in current `flow`
- `action_binding` -> `Barcode Flow Action Binding` in current `flow`
- `action` -> active `QR Action Definition`

Transition mode contracts:

- `binding_mode=mapping`
  - requires `field_map`
  - requires `target_doctype`
- `binding_mode=custom_handler`
  - requires `action_binding`
  - linked binding must use `trigger_event=custom_handler`
  - linked binding must define `custom_handler`
- `binding_mode=both`
  - requires `field_map`
  - requires `action_binding`
  - linked binding must use `trigger_event=custom_handler`
  - `target_doctype` is required unless the linked binding has `handler_override_wins=1`

Strict behavior:
- cross-flow links are rejected
- runtime uses the link fields directly
- legacy `source_node_key`, `target_node_key`, `condition_key`, `field_map_key`, `binding_key`, and `action_key` are not the primary configuration path

### 5. Add optional node/transition event bindings

After the core transitions exist, you can add secondary bindings for:
- `On Enter Node`
- `On Exit Node`
- `On Transition`

These are optional orchestration hooks. They must still remain flow-consistent:
- event binding `flow` must match the linked node or transition `flow`

### 6. Understand hard-delete blocks before cleanup

Delete guards are enforced on referenced records.

Blocked edges:
- deleting a node is blocked by:
  - `Transition.source_node`
  - `Transition.target_node`
  - `ActionBinding.target_node`
- deleting a condition is blocked by:
  - `Transition.condition`
- deleting a field map is blocked by:
  - `Transition.field_map`
- deleting an action binding is blocked by:
  - `Transition.action_binding`
- deleting a transition is blocked by:
  - `ActionBinding.target_transition`
- deleting a QR action definition is blocked by:
  - `Transition.action`
  - `ActionBinding.action`

Operational cleanup rule:
- detach or delete dependent records first
- then delete the now-unreferenced upstream record

## Configuration Example

### Direct ASN to Purchase Receipt

1. `Barcode Flow Definition`
   - `flow_name`: `Inbound::DirectPR::ASN`
   - one default scope:
     - `scope_key`: `direct-pr-default`
     - `source_doctype`: `ASN`
     - optional `company` / `warehouse` filters

2. `Barcode Flow Node`
   - `node_key=scan`
   - `node_key=pr_draft`

3. `Barcode Flow Field Map`
   - `map_key=asn-to-pr`
   - map source header/item values into `Purchase Receipt`

4. `QR Action Definition`
   - active row for `create_purchase_receipt`
   - `source_doctype=ASN`

5. `Barcode Flow Transition`
   - `source_node` -> `scan`
   - `target_node` -> `pr_draft`
   - `action` -> active `QR Action Definition` for `create_purchase_receipt`
   - `binding_mode=mapping`
   - `field_map` -> `asn-to-pr`
   - `target_doctype=Purchase Receipt`
   - `generation_mode=hybrid` or `runtime`

## Validation Semantics

### Same-flow integrity

The following must share the same flow as the transition:
- `source_node`
- `target_node`
- `condition`
- `field_map`
- `action_binding`

The following must share the same flow as the action binding:
- `target_node`
- `target_transition`

### Per-flow uniqueness

Business keys are unique per flow:
- `(flow, node_key)`
- `(flow, condition_key)`
- `(flow, map_key)`
- `(flow, binding_key)`
- `(flow, transition_key)`

Cross-flow reuse is allowed. Same-flow duplicates are rejected.

### Link-native runtime behavior

Current runtime/dispatch behavior assumes:
- source node state is available for dispatch matching
- transitions are queried by `flow + source_node + action`
- conditions are resolved by linked condition document
- field maps are resolved by linked field map document
- child scan-code generation derives action metadata from linked `QR Action Definition`

There is no broad `flow + action` fallback match when source node is missing.

## Desk Authoring Notes

- Always set `flow` first on standalone docs. The link pickers depend on it.
- If a transition link picker is empty, verify the linked record:
  - exists
  - belongs to the same flow
  - is the correct doctype
- For action links, only active `QR Action Definition` rows should be selected.

## Troubleshooting

### No matching flow

Typical cause:
- no active flow scope matched `source_doctype`, `company`, `warehouse`, or `supplier_type`

Check:
- scope filters are not overly narrow
- exactly one default scope exists when priorities tie

### Transition save rejected

Typical causes:
- missing `field_map` or `target_doctype` for `mapping`
- wrong binding trigger for handler modes
- cross-flow link selected manually

Check:
- `binding_mode`
- linked binding trigger
- linked record `flow`

### Dispatch says source node is required

Current matching is strict. The source document must expose current node state or the caller must provide it through the supported runtime path. There is no flow-wide fallback matcher anymore.

### Record cannot be deleted

The message names the blocking references. Remove or detach those references first, then retry the delete.
