# Barcode Process Flow One-Screen Hard-Cut Design

Date: 2026-04-22
Status: Approved for planning
Owner: ASN Module

## 1. Problem Statement

Current barcode flow authoring requires system managers to configure multiple low-level technical records (`Definition`, `Node`, `Transition`, `Action Binding`, `Condition`, `Field Map`, and action catalogs). This is powerful but not obvious for operations users.

The app is still under active development and not installed in production. We can take a hard-cut simplification path and remove legacy complexity.

## 2. First-Principles Goal

Barcode flow should represent one business intent:

- scanning a barcode on a source document should automate creation (or confirmation) of the next document(s) in the operation flow.

The setup must be obvious to a system manager:

- define transitions as `From DocType -> To DocType`
- optionally gate by condition
- optionally choose script override only for advanced logic

## 3. Scope

### In scope

- One-screen flow configuration model
- Native and custom document chains (including Gate Pass)
- Parallel branches from the same source doctype
- Item-level and aggregate conditions
- Standard handler catalog for common ERPNext operations (inbound, outbound, subcontracting, material request)
- ERPNext v15 + v16 compatibility with hidden unsupported options
- Hard cut removal of obsolete barcode-flow graph code and tests

### Out of scope (v1)

- Flow JSON import/export portability
- Backward compatibility with old barcode-flow relational graph records
- Dual runtime (old + new) in production path

## 4. Alternatives Considered

### Option A: Keep relational graph model and improve labels

- Pros:
  - minimal backend rework
  - lower immediate migration effort
- Cons:
  - user complexity remains high
  - still requires understanding technical graph concepts

### Option B: One-screen facade that writes old graph records

- Pros:
  - user UI simplified
  - old runtime reused
- Cons:
  - hidden complexity remains
  - harder debugging when generated records drift
  - two mental models to maintain

### Option C (selected): Hard cut to one-screen source-of-truth model

- Pros:
  - clearest UX and lowest long-term complexity
  - direct runtime over business-level rows
  - no graph indirection
- Cons:
  - destructive cutover for old model
  - larger initial refactor and test rewrite

Decision: **Option C**.

## 5. Target UX Model

## 5.1 Primary DocType

New doctype: `Barcode Process Flow`

Purpose: single setup surface for system manager.

Header fields:

- `flow_name` (Data, required)
- `is_active` (Check)
- `company` (Link Company, optional)
- `warehouse` (Link Warehouse, optional)
- `supplier_type` (Link Supplier Type or Data, optional)
- `description` (Small Text)

Child table: `Flow Step`

## 5.2 Flow Step Row (business-level transition)

Each row represents one transition:

- `from_doctype` (Link DocType, required)
- `to_doctype` (Link DocType, required)
- `label` (Data, optional)
- `execution_mode` (Select: `Mapping`, `Server Script`; default `Mapping`)
- `mapping_set` (Link `Barcode Mapping Set`, required when mode=`Mapping`)
- `server_script` (Link `Server Script`, required when mode=`Server Script`)
- `condition` (Link `Barcode Rule`, optional)
- `priority` (Int, default 100)
- `generate_next_barcode` (Check, default 1)
- `generation_mode` (Select: `immediate`, `runtime`, `hybrid`; default `hybrid`)
- `is_active` (Check, default 1)

### UX behavior

- Branching = multiple rows with same `from_doctype`
- Unsupported targets/actions for current ERP version are hidden from row pickers
- Irrelevant fields auto-hidden by `execution_mode`

## 5.3 Conditions

New doctype: `Barcode Rule`

Supports from day one:

- header rules
- item rules: `items_any`, `items_all`
- aggregate rules: `count`, `sum`, `min`, `max`, `avg`

This keeps business branching explicit without requiring scripts.

## 5.4 Mapping

New doctypes:

- `Barcode Mapping Set`
- `Barcode Mapping Row`

Mapping is picker-driven (no free-form dotted path typing in primary UX):

- source selector supports link traversal
- target selector supports header and item targets
- constants supported
- optional transforms from a controlled transform catalog

## 6. Runtime Semantics

## 6.1 Dispatch

On scan:

1. Resolve source document from scan token.
2. Identify active `Barcode Process Flow` records matching context.
3. Pick active `Flow Step` rows where `from_doctype == source_doc.doctype`.
4. Evaluate `condition` where present.
5. Resolve winners by highest priority (and deterministic tie-break).
6. Execute each winner according to mode:
   - `Mapping`: use standard pair handler if available, else generic mapping builder.
   - `Server Script`: call linked server script.
7. Return created document contract (`doctype`, `name`, `url`).
8. Generate child barcodes when enabled.
9. Write scan log with flow + step metadata.

Scan token contract in new model:

- replace action-key-centric token metadata with flow-step-centric metadata.
- token must identify source doc (`source_doctype`, `source_name`) and target execution step (`flow_step`).

## 6.2 No old graph dependencies

Runtime must not depend on:

- `Barcode Flow Definition`
- `Barcode Flow Node`
- `Barcode Flow Transition`
- `Barcode Flow Action Binding`
- old graph cache/repository/resolver modules

## 7. Standard Handler Catalog (maximum use-case coverage)

Built-in handler templates (internal catalog) used by `Mapping` mode for known pairs:

### Inbound and finance

- `ASN -> Purchase Receipt`
- `Purchase Receipt -> Purchase Invoice`
- `Purchase Receipt -> Quality Inspection`
- `Quality Inspection(accepted) -> Stock Entry (transfer)`
- `Quality Inspection(rejected) -> Purchase Return`

### Gate operations and outbound

- `Any configured source -> Gate Pass (Gate In)`
- `Any configured source -> Gate Pass (Gate Out)`
- `Delivery/Dispatch source -> dispatch status update`

### Subcontracting

- `Subcontracting Order -> Send to Subcontractor Stock Entry`
- `Subcontracting Order -> Subcontracting Receipt`
- `ASN -> Subcontracting Receipt` (requires subcontracting order context; fail closed when missing)

### Material Request (standard ERP paths)

- `Material Request(Purchase) -> Purchase Order`
- `Material Request(Purchase) -> Request for Quotation`
- `Material Request(Purchase) -> Supplier Quotation`
- `Material Request(Material Transfer) -> Stock Entry`
- `Material Request(Material Issue) -> Stock Entry`
- `Material Request(Customer Provided) -> Stock Entry (material receipt)`
- `Material Request(Material Transfer) -> In Transit Stock Entry`
- `Material Request(Manufacture) -> Work Order`
- `Material Request -> Pick List`
- `Material Request(Subcontracting) -> Purchase Order` (v16 capability only)

## 8. ERPNext v15/v16 Compatibility

Capability matrix is runtime-provided and drives UI filtering.

Rules:

- Unsupported transitions are hidden from pickers.
- Save-time and runtime validation still enforce capability constraints.
- v16-only MR subcontracting transitions are hidden in v15.

Known version differences accounted for:

- `Material Request` type `Subcontracting` exists in v16, not in v15.
- `make_purchase_order` behavior differs between v15 and v16 for subcontracting MR.

## 9. Hard-Cut Removal Plan

## 9.1 Remove old graph doctypes and related client scripts

- `asn_module/asn_module/doctype/barcode_flow_definition/*`
- `asn_module/asn_module/doctype/barcode_flow_scope/*`
- `asn_module/asn_module/doctype/barcode_flow_node/*`
- `asn_module/asn_module/doctype/barcode_flow_transition/*`
- `asn_module/asn_module/doctype/barcode_flow_action_binding/*`
- `asn_module/asn_module/doctype/barcode_flow_condition/*` (replaced by new `Barcode Rule`)
- `asn_module/asn_module/doctype/barcode_flow_field_map/*` (replaced by mapping-set model)
- `asn_module/public/js/doctype/barcode_flow_transition.js`
- `asn_module/public/js/doctype/barcode_flow_action_binding.js`

## 9.2 Remove old runtime modules

- `asn_module/barcode_flow/cache.py`
- `asn_module/barcode_flow/repository.py`
- `asn_module/barcode_flow/resolver.py`
- `asn_module/barcode_flow/runtime.py`
- `asn_module/barcode_flow/conditions.py`
- `asn_module/barcode_flow/mapping.py`
- `asn_module/barcode_flow/errors.py`

(and replace with new `barcode_process_flow/*` runtime package)

## 9.3 Remove obsolete compatibility/action-registry code

- `asn_module/asn_module/doctype/qr_action_registry/*`
- `asn_module/asn_module/doctype/qr_action_registry_item/*`
- `asn_module/asn_module/doctype/qr_action_definition/*`
- `asn_module/commands.py` registry drift checks tied to old graph/runtime
- old registry projection logic in `setup_actions.py` (replace with code-defined handler-template capability service)

## 9.4 Remove old tests and replace with new-model tests

Remove:

- `asn_module/barcode_flow/tests/*`
- `asn_module/property_tests/test_barcode_flow_properties.py`
- `asn_module/tests/integration/test_barcode_flow_integration.py`
- `asn_module/tests/integration/dispatch_flow.py`
- old doctype tests tied only to removed doctypes

Replace with:

- `barcode_process_flow` unit tests (schema, resolver, condition, mapping, runtime)
- integration tests for end-to-end scan dispatch using one-screen rows
- property tests for branching and condition determinism in new model
- compatibility tests for v15/v16 capability filtering

## 10. Data and Migration Policy

Because this is a development-stage module with no required production migration:

- no migration from old graph records
- destructive schema cleanup is allowed
- fixtures and tests must be rewritten to new model

## 11. Validation and Error Handling

- clear save-time errors for missing required mode fields
- clear scan-time errors for missing subcontracting context on `ASN -> Subcontracting Receipt`
- deterministic ambiguity errors include flow + step labels
- fail closed when no eligible step found

## 12. Performance Expectations

- query flow rows by `(is_active, from_doctype, company, warehouse, supplier_type)`
- cache capability matrix and flow-step graph per request/context
- avoid long-held DB locks in dispatch path

## 13. Risks and Mitigations

Risk: regression from hard cut

- Mitigation: remove old path completely, rewrite tests, and gate merge on new integration suite.

Risk: hidden version behavior surprises

- Mitigation: explicit capability matrix tests on bench15 and bench16.

Risk: mapper UX complexity in item mappings

- Mitigation: picker-only mapping authoring and server-script escape hatch.

## 14. Acceptance Criteria

1. System manager can configure a complete flow from one screen only.
2. No user-facing dependency on old graph doctypes.
3. Standard inbound/outbound/subcontracting/MR handlers available in picker for compatible ERP version.
4. Unsupported version paths are hidden from pickers.
5. Old graph code and tests are removed.
6. New runtime and test suite pass for bench15 and bench16.
