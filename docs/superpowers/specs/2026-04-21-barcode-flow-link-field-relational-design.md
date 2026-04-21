# Barcode Flow Link-Field Relational Redesign

Date: 2026-04-21  
Status: Approved for planning

## 1. Objective
Redesign Barcode Flow configuration from key-heavy child-table records to a link-first relational model so system managers can configure flows with `Link` pickers instead of manual text entry where possible.

This is a fresh-install-only change for an under-development module. Backward compatibility and data migration are intentionally out of scope.

## 2. Current Problem
Current `Barcode Flow` child records use many `Data` fields for references (`source_node_key`, `target_node_key`, `condition_key`, `field_map_key`, `binding_key`, `action_key`, `target_doctype`).

Consequences:
- High typo risk and invalid references.
- Weak admin UX (manual key entry instead of chooser).
- Validation burden pushed to runtime.

## 3. Decisions Locked
1. Full relational redesign (not partial).
2. Per-flow owned records (no global reusable library in v1).
3. Keep human-readable business keys (`node_key`, `transition_key`, etc.) for readability/search.
4. Deterministic semantic naming for standalone records.
5. Delete behavior: hard-block delete when entity has active inbound references.
6. Introduce a concrete linkable action catalog doctype: `QR Action Definition`.

## 4. Scope and Non-Goals
### In Scope
- Convert flow entities into standalone doctypes with flow-scoped links.
- Replace text reference fields with `Link` fields wherever resolvable.
- Preserve existing runtime behavior and condition semantics.
- Improve validation and admin ergonomics.

### Out of Scope
- Migration logic for existing installed sites.
- Global reusable flow entities across multiple flows.
- New feature semantics beyond schema/runtime alignment.

## 5. High-Level Architecture
`Barcode Flow Definition` remains the root aggregate.

Standalone child-like entities (normal doctypes, each linked to `Barcode Flow Definition`):
- `Barcode Flow Node`
- `Barcode Flow Condition`
- `Barcode Flow Field Map`
- `Barcode Flow Action Binding`
- `Barcode Flow Transition`

`Barcode Flow Transition` becomes the central linkage point with `Link` references to other flow entities.

## 6. Data Model Redesign

### 6.1 Barcode Flow Node
Fields:
- `name`: deterministic semantic autoname (derived from flow + node key)
- `flow` (`Link` -> `Barcode Flow Definition`, required)
- `node_key` (`Data`, required, unique within flow)
- `label` (`Data`, required)
- `node_type` (`Select`: Start/State/End, required)
- `description` (`Small Text`, optional)

### 6.2 Barcode Flow Condition
Fields:
- `name`: deterministic semantic autoname
- `flow` (`Link` -> `Barcode Flow Definition`, required)
- `condition_key` (`Data`, required, unique within flow)
- `scope` (`Select`, required)
- `field_path` (`Data`, required)
- `operator` (`Select`, required)
- `value` (`Small Text`, optional)
- `aggregate_fn` (`Select`, optional)

### 6.3 Barcode Flow Field Map
Fields:
- `name`: deterministic semantic autoname
- `flow` (`Link` -> `Barcode Flow Definition`, required)
- `map_key` (`Data`, required, unique within flow)
- `mapping_type` (`Select`, required)
- `source_field_path` (`Data`, optional)
- `target_field_path` (`Data`, required)
- `constant_value` (`Small Text`, optional)
- `transform_key` (`Data`, optional)

### 6.4 QR Action Definition (new)
Concrete, linkable action catalog used by flow transition and binding records.

Fields:
- `name`: deterministic semantic autoname
- `action_key` (`Data`, required, unique)
- `handler_method` (`Data`, required)
- `source_doctype` (`Link` -> `DocType`, required)
- `allowed_roles` (`Small Text`, required)
- `is_active` (`Check`)

`Barcode Flow Transition.action` and `Barcode Flow Action Binding.action` link to this doctype.

### 6.5 Barcode Flow Action Binding
Fields:
- `name`: deterministic semantic autoname
- `flow` (`Link` -> `Barcode Flow Definition`, required)
- `binding_key` (`Data`, required, unique within flow)
- `enabled` (`Check`)
- `trigger_event` (`Select`, required)
- `target_node` (`Link` -> `Barcode Flow Node`, optional)
- `target_transition` (`Link` -> `Barcode Flow Transition`, optional)
- `action` (`Link` -> `QR Action Definition`, required)
- `custom_handler` (`Data`, optional)
- `handler_override_wins` (`Check`)

Event semantics:
- `trigger_event=custom_handler`: transition-level handler binding. Must not set `target_node` or `target_transition`.
- `trigger_event=On Enter Node` / `On Exit Node`: requires `target_node`.
- `trigger_event=On Transition`: requires `target_transition`.

### 6.6 Barcode Flow Transition
Fields:
- `name`: deterministic semantic autoname
- `flow` (`Link` -> `Barcode Flow Definition`, required)
- `transition_key` (`Data`, required, unique within flow)
- `generation_mode` (`Select`, required)
- `source_node` (`Link` -> `Barcode Flow Node`, required)
- `target_node` (`Link` -> `Barcode Flow Node`, required)
- `action` (`Link` -> `QR Action Definition`, required)
- `target_doctype` (`Link` -> `DocType`, optional/required by mode)
- `binding_mode` (`Select`, required)
- `condition` (`Link` -> `Barcode Flow Condition`, optional)
- `field_map` (`Link` -> `Barcode Flow Field Map`, optional)
- `action_binding` (`Link` -> `Barcode Flow Action Binding`, optional)
- `priority` (`Int`)

## 7. Validation Rules

### 7.1 Cross-Flow Integrity
All links on transition/binding must point to records with the same `flow`. Any mismatch is blocked at save time.

### 7.2 Mode-Driven Requirements
- `binding_mode=mapping`: requires `field_map` and valid `target_doctype`.
- `binding_mode=custom_handler`: requires `action_binding` with `trigger_event=custom_handler` and handler contract.
- `binding_mode=both`: enforce both sides with existing override semantics.
- `custom_handler` bindings may be created before transitions and then linked by transition.
- Node/transition event bindings are independent runtime hooks and are not the transition-level `action_binding` reference.

### 7.3 Delete Rules (Hard Block)
Deletion is blocked for the following dependency edges:
- `Barcode Flow Node` if referenced by any transition (`source_node`/`target_node`) or action binding (`target_node`).
- `Barcode Flow Condition`, `Field Map`, or `Action Binding` if referenced by any transition.
- `Barcode Flow Transition` if referenced by any action binding (`target_transition`).
- `QR Action Definition` if referenced by any transition or action binding.

Error message must include impacted `transition_key` values.

### 7.4 Key Uniqueness
Unique constraints per `flow` for:
- `node_key`
- `condition_key`
- `map_key`
- `binding_key`
- `transition_key`

## 8. Runtime Behavior
Behavior remains semantically equivalent; lookup mechanism changes from key-resolution maps to linked-doc resolution.

Execution flow:
1. Resolve active flow via scope.
2. Resolve transition candidates by `flow` + source node/action context.
3. Apply linked condition (if present).
4. Execute mapping/handler via linked map/binding records.
5. Emit scan log metadata (flow, transition, scope key) with business keys for readability.

## 9. UI/Admin UX
- Transition form uses `Link` pickers filtered by `flow`.
- Action/doctype fields use native link dialogs.
- Business keys stay visible in list/search for human-friendly operations.
- Setup flow (authoring order):
  1. Create flow.
  2. Create nodes, conditions, field maps.
  3. Create `QR Action Definition` records.
  4. Create transitions.
  5. Create action bindings:
     - custom handler bindings can be linked from transitions.
     - node/transition event bindings can target existing nodes/transitions.

## 10. Indexing and Performance
Add indexes to keep dispatch-time queries deterministic and fast:
- `Transition(flow, source_node, priority)`
- `Transition(flow, transition_key)` unique
- `Node(flow, node_key)` unique
- `Condition(flow, condition_key)` unique
- `FieldMap(flow, map_key)` unique
- `ActionBinding(flow, binding_key)` unique

Trade-off: more indexes increase write overhead modestly, but configuration writes are rare and dispatch reads are frequent; this is acceptable.

## 11. Testing Strategy

### Unit
- Doctype validation for same-flow links.
- Mode requirement enforcement.
- Delete hard-block checks with dependent transition keys.
- Uniqueness constraints per flow.

### Integration
- Existing gate-in/direct-PR/gate-out flow scenarios run on relational schema.
- Item-level and aggregate condition evaluation remains correct.
- Resolver and transition matching remain deterministic.

### Property
- Resolver and condition invariants continue to hold under relational references.

### Quality Gates
- Targeted module suites.
- Full app smoke.
- `pre-commit run --all-files`.

## 12. Trade-offs
- Chosen: stronger relational integrity + better UX.
- Cost: larger schema/runtime refactor and more doctypes.
- Accepted because module is pre-production and fresh-install only.

## 13. Planning Readiness
This spec is focused enough for a single implementation plan and does not mix independent subsystems.
