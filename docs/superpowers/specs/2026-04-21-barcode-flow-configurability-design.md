# Barcode Flow Configurability Design

Date: 2026-04-21
Status: Approved for planning
Owner: ASN Module

## 1. Problem Statement

The current ASN module supports QR/barcode dispatch with a generic action registry, but end-to-end document progression is still mostly hardcoded in handlers (for example ASN -> PR, PR -> PI). This limits extensibility for client-specific processes such as:

- Inbound with custom Gate Pass (`Gate In`) before Purchase Receipt
- Inbound without Gate Pass (direct ASN -> Purchase Receipt)
- Outbound dispatch with Gate Pass (`Gate Out`)
- Branching paths from one document (for example PR -> PI and PR -> Stock Transfer/Putaway)

Goal: let System Manager configure barcode-driven document flows without changing module code for each new process variation.

## 2. Goals and Non-Goals

### Goals

- Add user-configurable barcode workflow graph with branching paths.
- Support context-scoped routing (company/warehouse/supplier-type style scoping).
- Support both:
  - UI field mapping for common target document creation
  - Optional custom Python handler override for complex transitions
- Support day-one header and item-level/aggregate transition conditions.
- Keep current dispatch endpoint and scan log model as core execution path.
- Default transition generation mode to Hybrid (pre-generate + runtime re-validation).

### Non-Goals

- No backward compatibility migration from production installs (project is under development).
- No replacement of ERPNext native Workflow doctype.
- No arbitrary Python expression execution from UI conditions/mappings.

## 3. Naming Decision

Avoid `Workflow` naming to prevent confusion with ERPNext native Workflow.

Chosen namespace: `Barcode Flow *`

Primary options considered:

1. `Barcode Flow *` (chosen)
2. `Scan Flow *`

Trade-off:

- `Barcode Flow *` is more explicit and less ambiguous, but longer names.

## 4. Architecture Overview

Execution layer remains:

- `Scan Code` doctype (code registry and lifecycle)
- `Scan Log` doctype (execution audit)
- `asn_module.qr_engine.dispatch.dispatch` (scan entrypoint)
- `QR Action Registry` (low-level action catalog + role controls)

New layer added:

- `Barcode Flow *` doctypes for graph definition, routing scope, conditions, and field mapping.

Design principle:

- Keep token/scan execution path stable.
- Move document progression semantics from hardcoded handlers into declarative graph config.

## 5. Data Model

## 5.1 `Barcode Flow Definition`

Top-level flow container.

Suggested fields:

- `flow_name` (Data, unique)
- `is_active` (Check)
- `description` (Small Text)
- `default_generation_mode` (Select: immediate/runtime/hybrid, default hybrid)
- `version_no` (Int or Data for cache invalidation)

## 5.2 `Barcode Flow Scope`

Context-based selection rules for which flow applies.

Suggested fields:

- `parent_flow` (Link: Barcode Flow Definition)
- `is_enabled` (Check)
- `priority` (Int, higher wins)
- `company` (Link Company, optional)
- `warehouse` (Link Warehouse, optional)
- `supplier_type` (Link Supplier Type, optional)
- `additional_context_json` (optional extension, controlled)

Scope matching behavior:

- Null field means wildcard.
- Winner chosen by specificity, then priority, then modified timestamp.
- Ties after all rules -> block with explicit ambiguous configuration error.

## 5.3 `Barcode Flow Node`

Represents logical state/document milestone.

Suggested fields:

- `parent_flow` (Link)
- `node_key` (Data, unique within flow)
- `source_doctype` (Link DocType)
- `source_docstatus` (optional Select)
- `is_start_node` (Check)
- `is_terminal` (Check)

## 5.4 `Barcode Flow Transition`

Directed edge from one node to next target creation action.

Suggested fields:

- `parent_flow` (Link)
- `from_node` (Link Barcode Flow Node)
- `to_node` (Link Barcode Flow Node)
- `transition_key` (Data, unique within flow)
- `is_enabled` (Check)
- `generation_mode` (Select: immediate/runtime/hybrid; default from flow)
- `allow_loop` (Check, default false)
- `action_key` (Data; validated against `QR Action Registry` action keys)
- `display_label` (Data for operator-facing scan labels)

## 5.5 `Barcode Flow Condition`

Conditional gating for transitions.

Suggested fields:

- `transition` (Link Barcode Flow Transition)
- `is_enabled` (Check)
- `sequence` (Int)
- `scope` (Select: header/items_any/items_all/items_aggregate)
- `field_path` (Data)
- `operator` (Select: =, !=, >, >=, <, <=, in, contains, is_set)
- `value_type` (Select: literal/field_ref/expression)
- `value` (Small Text)
- `logical_group` (Data/Int for grouping)
- `aggregate_fn` (optional Select: exists/count/sum)
- `aggregate_filter` (optional)

## 5.6 `Barcode Flow Field Map`

Mapping for target document creation.

Suggested fields:

- `transition` (Link Barcode Flow Transition)
- `sequence` (Int)
- `target_field` (Data)
- `mapping_type` (Select: source_field/constant/template/computed_builtin)
- `source_path` (Data)
- `constant_value` (Small Text)
- `template_expr` (Small Text)
- `required` (Check)
- `default_if_empty` (Small Text)

## 5.7 `Barcode Flow Action Binding`

Execution strategy for transition.

Suggested fields:

- `transition` (Link Barcode Flow Transition)
- `binding_mode` (Select: mapping/custom_handler/both)
- `custom_handler` (Data: dotted path)
- `handler_override_wins` (Check; default true)

## 6. Runtime Execution Algorithm

Entry remains: `dispatch(code, device_info)`.

Steps:

1. Resolve and validate scan code from `Scan Code`.
2. Resolve action metadata from `QR Action Registry`, validate role permission.
3. Read source document context and resolve single active `Barcode Flow Definition` via `Barcode Flow Scope`.
4. Resolve the active transition in the selected flow by exact match:
   - `action_key == scan_code.action_key`
   - node `source_doctype == scan_code.source_doctype`
   - node identity alignment to `scan_code.source_name`
5. If no active flow or no unique transition matches, fail fast with explicit admin-facing configuration error.
6. Execute transition binding:
   - mapping engine for standard target creation, or
   - custom handler override for advanced logic.
7. Evaluate outgoing transitions from resulting node.
8. Generate next-step scan codes by transition generation mode:
   - immediate: generate now
   - runtime: no pre-generation
   - hybrid: generate now and still enforce runtime conditions when scanned
9. Persist execution details in `Scan Log`.
10. Return created/opened document payload as current API contract.

Transaction and idempotency rule:

- Dispatch must keep DB work short and deterministic.
- Creation handlers must remain idempotent (re-open existing draft where appropriate) to tolerate repeat scans and concurrent scans.

## 7. Condition and Mapping Semantics

## 7.1 Condition Evaluation

Supported scopes:

- `header`: source doc fields
- `items_any`: condition true for at least one item row
- `items_all`: condition true for all item rows
- `items_aggregate`: aggregate check with built-ins

Built-in aggregates (v1):

- `exists(items where ...)`
- `count(items where ...)`
- `sum(items.<numeric_field> where ...)`

Example day-one condition:

- Any item requires inspection:
  - `scope=items_any`
  - `field_path=inspection_required_before_purchase`
  - `operator==`
  - `value=true`

## 7.2 Mapping

Mapping modes:

- source field pass-through
- constants (for example `entry_type = "Gate In"`)
- safe templates
- limited computed built-ins

Security model:

- no arbitrary code execution from UI-defined expressions
- validate field paths against DocType metadata at save-time

## 8. Applied Business Scenarios

## 8.1 Inbound With Gate Pass

Configured path:

- `ASN Barcode` -> `Gate Pass (Gate In)` -> `Purchase Receipt` -> (`Purchase Invoice`, `Stock Transfer/Putaway`)

Transition mapping examples:

- ASN to Gate Pass:
  - constant: `entry_type = Gate In`
  - mapped: supplier/invoice/transporter/vehicle details

## 8.2 Inbound Without Gate Pass

Alternate scoped flow:

- `ASN Barcode` -> `Purchase Receipt`

Selected by scope where gate pass path is not applicable.

## 8.3 PR Branching

From `Purchase Receipt Submitted` node:

- Transition A: PR -> Purchase Invoice (condition `per_billed < 100`)
- Transition B: PR -> Stock Transfer/Putaway (inspection/warehouse conditions)

Default mode: hybrid for both transitions.

## 8.4 Outbound Dispatch / Gate Out

Configured path:

- `Dispatch Barcode` -> `Gate Pass (Gate Out)` -> mark dispatched + optional downstream nodes

## 9. Validation and Governance

Save-time checks:

- Transition references valid nodes and action bindings.
- Graph acyclic unless transition explicitly marked loop-enabled.
- No unresolved custom handler dotted paths.
- Condition operators/fields valid for referenced source DocType.
- Scope rules do not create unresolved ambiguity for same priority/specificity.

Runtime checks:

- Role permission enforcement remains mandatory.
- Hybrid/runtime condition re-validation on scan remains mandatory.
- Missing DocType/module in transition path -> clear user/admin error + log.
- Idempotent behavior preserved (open existing draft where applicable).
- Any scope/transition ambiguity is treated as configuration error, never as runtime best-effort guess.

## 10. Performance and Indexing

Existing:

- `Scan Code` already has composite index `(action_key, source_doctype, source_name, status)`.

Additions:

- `Scan Code`: index `(status, expires_on)` for lifecycle operations.
- `Barcode Flow Transition`: `(from_node, is_enabled, generation_mode)`.
- `Barcode Flow Scope`: `(is_enabled, priority, company, warehouse, supplier_type)`.
- `Barcode Flow Condition`: `(transition, is_enabled, scope, sequence)`.

Caching:

- Cache compiled active flow graph by `(flow_definition, version_no/hash)`.
- Invalidate cache on update to any `Barcode Flow *` record.

Trade-off:

- More indexes increase write overhead on config edits but improve scan-time performance and predictability.

## 11. Observability

Extend logging context (in `Scan Log` or linked detail):

- selected flow definition
- selected transition
- scope match key
- condition evaluation summary
- generation mode used

Purpose:

- make scan routing decisions auditable and debuggable for operations teams.

## 12. Testing Strategy

Unit tests:

- scope resolution precedence and ambiguity handling
- condition evaluator: header/items_any/items_all/items_aggregate
- mapping engine: constants, source fields, required/default handling

Integration tests:

- gate-pass-enabled inbound route
- gate-pass-disabled inbound route
- PR branching with hybrid generation and runtime rejection
- outbound gate-out route

Property tests:

- scope overlap edge cases
- condition boundary and aggregate combinations

## 13. Trade-offs Summary

Chosen design trade-offs:

- Prefer explicit config + strict validation over permissive runtime guessing.
- Prefer constrained DSL over unrestricted expressions for safety and maintainability.
- Prefer hybrid generation default for operations speed while keeping runtime correctness checks.
- Prefer context scoping in v1 for business realism, accepting extra admin governance complexity.

## 14. Implementation Readiness

Design approved in brainstorming session.
Next step: create a phased implementation plan (schema, evaluator, runtime integration, UI, tests).
