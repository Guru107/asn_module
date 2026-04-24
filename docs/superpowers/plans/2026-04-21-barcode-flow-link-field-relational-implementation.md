# Barcode Flow Link-Field Relational Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Status:** Superseded by `docs/superpowers/plans/2026-04-22-barcode-process-flow-one-screen-hard-cut-implementation.md`.
> This document is archived for historical context and intentionally contains pre-hard-cut `barcode_flow` paths.

**Goal:** Replace key-based Barcode Flow child-table references with a link-first relational model so admins configure flows via `Link` fields with stronger integrity and less manual typing.

**Architecture:** Keep `Barcode Flow Definition` as the root aggregate for scope resolution, but move nodes/transitions/conditions/field maps/action bindings to standalone doctypes linked by `flow`. Add a concrete linkable action catalog (`QR Action Definition`) as source of truth, and keep `QR Action Registry` as a compatibility projection synced from the new catalog. Refactor dispatch/runtime/caching to resolve by linked docs instead of text keys while preserving behavior and scan-log semantics.

**Tech Stack:** Frappe v16 DocTypes + controllers + doctype JS query filters, Python services (`asn_module/barcode_flow`, `asn_module/qr_engine`), Frappe tests (`bench run-tests --lightmode`), pre-commit (ruff/eslint/prettier).

---

## Scope Check (Locked)
This is one subsystem (Barcode Flow schema + runtime alignment). It is safe to implement as one plan with isolated tasks.

## File Structure (Locked Before Implementation)

### New / Expanded Model
- Create: `asn_module/asn_module/doctype/qr_action_definition/`
- Modify: `asn_module/asn_module/doctype/barcode_flow_node/{barcode_flow_node.json,barcode_flow_node.py}`
- Modify: `asn_module/asn_module/doctype/barcode_flow_transition/{barcode_flow_transition.json,barcode_flow_transition.py}`
- Modify: `asn_module/asn_module/doctype/barcode_flow_condition/{barcode_flow_condition.json,barcode_flow_condition.py}`
- Modify: `asn_module/asn_module/doctype/barcode_flow_field_map/{barcode_flow_field_map.json,barcode_flow_field_map.py}`
- Modify: `asn_module/asn_module/doctype/barcode_flow_action_binding/{barcode_flow_action_binding.json,barcode_flow_action_binding.py}`
- Modify: `asn_module/asn_module/doctype/barcode_flow_definition/{barcode_flow_definition.json,barcode_flow_definition.py}`

### UI Query Filters
- Create: `asn_module/public/js/doctype/barcode_flow_transition.js`
- Create: `asn_module/public/js/doctype/barcode_flow_action_binding.js`
- Modify: `asn_module/hooks.py` (register doctype_js)

### Runtime / Query Layer
- Create: `asn_module/barcode_flow/repository.py`
- Modify: `asn_module/barcode_flow/cache.py`
- Modify: `asn_module/barcode_flow/resolver.py`
- Modify: `asn_module/barcode_flow/runtime.py`
- Modify: `asn_module/qr_engine/dispatch.py`
- Modify: `asn_module/setup_actions.py`
- Modify: `asn_module/setup.py`

### Tests
- Create: `asn_module/asn_module/doctype/qr_action_definition/test_qr_action_definition.py`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`
- Modify: `asn_module/barcode_flow/tests/test_resolver.py`
- Modify: `asn_module/barcode_flow/tests/test_runtime.py`
- Modify: `asn_module/barcode_flow/tests/test_mapping.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch_errors.py`
- Modify: `asn_module/tests/integration/fixtures.py`
- Modify: `asn_module/tests/integration/test_barcode_flow_integration.py`
- Modify: `asn_module/tests/integration/test_dispatch_actions_integration.py`
- Modify: `asn_module/tests/test_setup_actions.py`
- Modify: `asn_module/property_tests/test_barcode_flow_properties.py`

### Docs
- Modify: `docs/BarcodeFlowConfiguration.md`
- Modify: `docs/ProjectOverview.md`

---

### Task 1: Add `QR Action Definition` Source-of-Truth Catalog

**Files:**
- Create: `asn_module/asn_module/doctype/qr_action_definition/qr_action_definition.json`
- Create: `asn_module/asn_module/doctype/qr_action_definition/qr_action_definition.py`
- Create: `asn_module/asn_module/doctype/qr_action_definition/test_qr_action_definition.py`
- Modify: `asn_module/setup_actions.py`
- Modify: `asn_module/setup.py`
- Modify: `asn_module/tests/test_setup_actions.py`

- [ ] **Step 1: Write failing tests for unique action keys and registry projection (@superpowers:test-driven-development)**

```python
def test_action_key_unique():
    make_action_definition(action_key="create_purchase_receipt")
    with pytest.raises(frappe.UniqueValidationError):
        make_action_definition(action_key="create_purchase_receipt")


def test_register_actions_syncs_registry_from_qr_action_definition():
    seed_qr_action_definition_rows()
    register_actions()
    reg = frappe.get_single("QR Action Registry")
    assert sorted(r.action_key for r in reg.actions) == sorted(expected_keys)
```

- [ ] **Step 2: Run tests and verify failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --module asn_module.tests.test_setup_actions --lightmode
```
Expected: FAIL before doctype/sync refactor.

- [ ] **Step 3: Implement doctype and sync function**

```python
class QRActionDefinition(Document):
    def validate(self):
        self.action_key = (self.action_key or "").strip()
        if not self.action_key:
            frappe.throw(_("Action Key is required"))
```

```python
def register_actions():
    actions = frappe.get_all("QR Action Definition", filters={"is_active": 1}, fields=[...])
    # replace singleton rows from source-of-truth catalog
```

- [ ] **Step 4: Re-run tests**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.tests.test_setup_actions --lightmode
bench --site dev.localhost run-tests --module asn_module.asn_module.doctype.qr_action_definition.test_qr_action_definition --lightmode
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/qr_action_definition asn_module/setup_actions.py asn_module/setup.py asn_module/tests/test_setup_actions.py
git commit -m "feat(actions): add qr action definition source-of-truth catalog"
```

---

### Task 2: Convert Flow Entities to Standalone Relational DocTypes

**Files:**
- Modify: `asn_module/asn_module/doctype/barcode_flow_{node,transition,condition,field_map,action_binding}/*.json`
- Modify: `asn_module/asn_module/doctype/barcode_flow_{node,transition,condition,field_map,action_binding}/*.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_definition/{barcode_flow_definition.json,barcode_flow_definition.py}`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`

- [ ] **Step 1: Write failing schema tests for required `flow` links and link-field replacement**

```python
def test_transition_references_links_not_key_data_fields():
    meta = frappe.get_meta("Barcode Flow Transition")
    assert meta.get_field("source_node").fieldtype == "Link"
    assert meta.get_field("action").options == "QR Action Definition"


def test_node_requires_flow_link():
    node = frappe.get_doc({"doctype": "Barcode Flow Node", "node_key": "scan"})
    with pytest.raises(frappe.ValidationError):
        node.insert(ignore_permissions=True)


def test_deterministic_semantic_autoname_for_node():
    node = make_node(flow="Inbound-ACME", node_key="scan")
    assert node.name == "FLOW-Inbound-ACME-NODE-scan"
```

- [ ] **Step 2: Run schema tests and confirm failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Implement relational schema shape**

```python
# examples
# Barcode Flow Transition: source_node, target_node, condition, field_map, action_binding, action, target_doctype
# Barcode Flow Definition: retain scopes table only; remove embedded nodes/transitions/conditions/maps/bindings tables
# deterministic semantic autoname per standalone doctype
```

Autoname rules to implement and test:
- `FLOW-<flow>-NODE-<node_key>`
- `FLOW-<flow>-COND-<condition_key>`
- `FLOW-<flow>-MAP-<map_key>`
- `FLOW-<flow>-BIND-<binding_key>`
- `FLOW-<flow>-TRANS-<transition_key>`
- `ACT-<action_key>` for `QR Action Definition`

- [ ] **Step 4: Apply schema to site**

Run:
```bash
bench --site dev.localhost migrate
```
Expected: PASS.

- [ ] **Step 5: Re-run schema tests**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add asn_module/asn_module/doctype/barcode_flow_definition asn_module/asn_module/doctype/barcode_flow_node asn_module/asn_module/doctype/barcode_flow_transition asn_module/asn_module/doctype/barcode_flow_condition asn_module/asn_module/doctype/barcode_flow_field_map asn_module/asn_module/doctype/barcode_flow_action_binding asn_module/barcode_flow/tests/test_schema.py
git commit -m "feat(barcode-flow): convert flow entities to standalone relational doctypes"
```

---

### Task 3: Implement Mode-Driven Validation Contracts

**Files:**
- Modify: `asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`

- [ ] **Step 1: Add failing validation tests for binding/trigger contracts**

```python
def test_mapping_mode_requires_field_map_and_target_doctype():
    t = make_transition(binding_mode="mapping", field_map=None, target_doctype=None)
    with pytest.raises(frappe.ValidationError):
        t.insert(ignore_permissions=True)


def test_custom_handler_mode_requires_custom_handler_binding():
    b = make_action_binding(trigger_event="On Enter Node")
    t = make_transition(binding_mode="custom_handler", action_binding=b.name)
    with pytest.raises(frappe.ValidationError):
        t.insert(ignore_permissions=True)
```

- [ ] **Step 2: Run schema tests and confirm failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Implement validation methods**

```python
class BarcodeFlowTransition(Document):
    def validate(self):
        self._validate_same_flow_links()
        self._validate_mode_contract()
```

```python
class BarcodeFlowActionBinding(Document):
    def validate(self):
        self._validate_trigger_contract()
```

- [ ] **Step 4: Re-run schema tests**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py asn_module/barcode_flow/tests/test_schema.py
git commit -m "feat(barcode-flow): enforce mode and trigger validation contracts"
```

---

### Task 4: Add Flow-Scoped Uniqueness and Dispatch Indexes

**Files:**
- Modify: `asn_module/asn_module/doctype/barcode_flow_node/barcode_flow_node.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_condition/barcode_flow_condition.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_field_map/barcode_flow_field_map.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py`
- Create: `asn_module/patches/post_model_sync/2026_04_21_add_barcode_flow_indexes.py`
- Modify: `asn_module/patches.txt`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`

- [ ] **Step 1: Add failing tests for per-flow unique key constraints**

```python
def test_node_key_unique_within_same_flow():
    make_node(flow=f1.name, node_key="scan")
    with pytest.raises(frappe.UniqueValidationError):
        make_node(flow=f1.name, node_key="scan")


def test_node_key_can_repeat_across_different_flows():
    make_node(flow=f1.name, node_key="scan")
    make_node(flow=f2.name, node_key="scan")
```

- [ ] **Step 2: Run tests and confirm failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Implement uniqueness validation + index installer**

```python
# per doctype validate: enforce uniqueness of (flow, *_key)
# add post_model_sync patch and register in patches.txt so index creation runs during migrate
# patch creates composite UNIQUE indexes for business keys:
# transition(flow, transition_key) UNIQUE
# node(flow, node_key) UNIQUE
# condition(flow, condition_key) UNIQUE
# field_map(flow, map_key) UNIQUE
# action_binding(flow, binding_key) UNIQUE
# and non-unique dispatch performance index:
# transition(flow, source_node, priority)
```

- [ ] **Step 4: Re-run tests and check index creation path**

Run:
```bash
bench --site dev.localhost migrate
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
bench --site dev.localhost execute "asn_module.patches.post_model_sync.2026_04_21_add_barcode_flow_indexes.verify_indexes"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/barcode_flow_node/barcode_flow_node.py asn_module/asn_module/doctype/barcode_flow_condition/barcode_flow_condition.py asn_module/asn_module/doctype/barcode_flow_field_map/barcode_flow_field_map.py asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py asn_module/patches/post_model_sync/2026_04_21_add_barcode_flow_indexes.py asn_module/patches.txt asn_module/barcode_flow/tests/test_schema.py
git commit -m "feat(barcode-flow): enforce per-flow uniqueness and add query indexes"
```

---

### Task 5: Add Flow-Scoped Link Picker Filters in Desk UI

**Files:**
- Create: `asn_module/public/js/doctype/barcode_flow_transition.js`
- Create: `asn_module/public/js/doctype/barcode_flow_action_binding.js`
- Modify: `asn_module/hooks.py`

- [ ] **Step 1: Add failing UI integration assertion for flow-scoped queries**

```python
# test should assert query filters include current flow on source_node/target_node/condition/field_map/action_binding
```

- [ ] **Step 2: Implement transition and action-binding doctype JS query filters**

```javascript
frappe.ui.form.on("Barcode Flow Transition", {
  setup(frm) {
    frm.set_query("source_node", () => ({ filters: { flow: frm.doc.flow } }));
    frm.set_query("target_node", () => ({ filters: { flow: frm.doc.flow } }));
  },
});
```

- [ ] **Step 3: Register doctype JS in hooks**

```python
doctype_js = {
  "Barcode Flow Transition": "public/js/doctype/barcode_flow_transition.js",
  "Barcode Flow Action Binding": "public/js/doctype/barcode_flow_action_binding.js",
}
```

- [ ] **Step 4: Build assets and sanity-check**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench build --app asn_module
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/public/js/doctype/barcode_flow_transition.js asn_module/public/js/doctype/barcode_flow_action_binding.js asn_module/hooks.py
git commit -m "feat(barcode-flow): add flow-scoped link query filters in doctype forms"
```

---

### Task 6: Enforce Hard-Block Delete Rules for Referenced Records

**Files:**
- Modify: `asn_module/asn_module/doctype/barcode_flow_node/barcode_flow_node.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_condition/barcode_flow_condition.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_field_map/barcode_flow_field_map.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py`
- Modify: `asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py`
- Modify: `asn_module/asn_module/doctype/qr_action_definition/qr_action_definition.py`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`

- [ ] **Step 1: Add failing tests for all blocked dependency edges**

```python
def test_delete_transition_blocked_if_targeted_by_action_binding():
    b = make_action_binding(trigger_event="On Transition", target_transition=t.name)
    with pytest.raises(frappe.ValidationError, match=b.binding_key):
        t.delete()
```

- [ ] **Step 2: Run tests and verify failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Implement `on_trash` guard checks and explicit dependency messages**

- [ ] **Step 4: Re-run tests**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/barcode_flow_node/barcode_flow_node.py asn_module/asn_module/doctype/barcode_flow_condition/barcode_flow_condition.py asn_module/asn_module/doctype/barcode_flow_field_map/barcode_flow_field_map.py asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.py asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.py asn_module/asn_module/doctype/qr_action_definition/qr_action_definition.py asn_module/barcode_flow/tests/test_schema.py
git commit -m "feat(barcode-flow): hard-block deletion of referenced relational records"
```

---

### Task 7: Build Repository + Cache Layer for Relational Graph Access

**Files:**
- Create: `asn_module/barcode_flow/repository.py`
- Modify: `asn_module/barcode_flow/cache.py`
- Modify: `asn_module/barcode_flow/tests/test_runtime.py`

- [ ] **Step 1: Add failing tests for flow-scoped transition and condition retrieval**

```python
def test_get_transitions_for_source_node_and_action_is_flow_scoped():
    rows = get_transitions_for_source_node_action(flow=flow.name, source_node=node.name, action=action.name)
    assert [r.name for r in rows] == [expected_transition.name]
```

- [ ] **Step 2: Run runtime tests and verify failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_runtime --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Implement repository helpers and cache adapters**

```python
def get_transitions_for_source_node_action(*, flow: str, source_node: str, action: str) -> list[Document]:
    ...

def get_condition(condition_name: str) -> Document | None:
    ...
```

- [ ] **Step 4: Re-run runtime tests**

Run: same command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/repository.py asn_module/barcode_flow/cache.py asn_module/barcode_flow/tests/test_runtime.py
git commit -m "feat(barcode-flow): add relational repository/cache graph access helpers"
```

---

### Task 8: Refactor Resolver, Runtime, and Dispatch to Link-Based Model

**Files:**
- Modify: `asn_module/barcode_flow/resolver.py`
- Modify: `asn_module/barcode_flow/runtime.py`
- Modify: `asn_module/barcode_flow/mapping.py`
- Modify: `asn_module/qr_engine/dispatch.py`
- Modify: `asn_module/barcode_flow/tests/test_resolver.py`
- Modify: `asn_module/barcode_flow/tests/test_runtime.py`
- Modify: `asn_module/barcode_flow/tests/test_mapping.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch.py`
- Modify: `asn_module/qr_engine/tests/test_dispatch_errors.py`

- [ ] **Step 1: Add failing tests for link-native transition resolution and execution**

```python
def test_resolve_matching_transition_uses_source_node_link_and_action_link():
    transition = resolve_matching_transition(...)
    assert transition.source_node == node.name
```

- [ ] **Step 2: Run targeted modules and confirm failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_resolver --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_runtime --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_mapping --lightmode
bench --site dev.localhost run-tests --module asn_module.qr_engine.tests.test_dispatch --lightmode
bench --site dev.localhost run-tests --module asn_module.qr_engine.tests.test_dispatch_errors --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Refactor resolver/runtime/dispatch to consume repository + links**

```python
# dispatch: resolve action from QR Action Definition
# runtime: resolve condition/map/binding docs from link names
# transition match: by flow + source_node + action, then condition check + priority tie-break
```

- [ ] **Step 4: Re-run targeted modules**

Run: same commands as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/resolver.py asn_module/barcode_flow/runtime.py asn_module/barcode_flow/mapping.py asn_module/qr_engine/dispatch.py asn_module/barcode_flow/tests/test_resolver.py asn_module/barcode_flow/tests/test_runtime.py asn_module/barcode_flow/tests/test_mapping.py asn_module/qr_engine/tests/test_dispatch.py asn_module/qr_engine/tests/test_dispatch_errors.py
git commit -m "refactor(barcode-flow): execute relational link-based transition graph"
```

---

### Task 9: Migrate Integration Fixtures and Flows to Relational Authoring Order

**Files:**
- Modify: `asn_module/tests/integration/fixtures.py`
- Modify: `asn_module/tests/integration/test_barcode_flow_integration.py`
- Modify: `asn_module/tests/integration/test_dispatch_actions_integration.py`
- Modify: `asn_module/tests/integration/dispatch_flow.py`

- [ ] **Step 1: Add failing integration tests that assert relational creation order and flow isolation**

```python
def test_fixture_builds_nodes_then_custom_handler_bindings_then_transitions():
    route = ensure_scoped_flow_route_fixtures(...)
    assert frappe.db.exists("Barcode Flow Action Binding", {"flow": route.flow_name, "trigger_event": "custom_handler"})
```

- [ ] **Step 2: Run integration suites and verify failure**

Run:
```bash
bench --site dev.localhost run-tests --module asn_module.tests.integration.test_barcode_flow_integration --lightmode
bench --site dev.localhost run-tests --module asn_module.tests.integration.test_dispatch_actions_integration --lightmode
```
Expected: FAIL.

- [ ] **Step 3: Refactor fixture builders to standalone docs + deterministic semantic names**

- [ ] **Step 4: Re-run integration suites**

Run: same commands as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/tests/integration/fixtures.py asn_module/tests/integration/test_barcode_flow_integration.py asn_module/tests/integration/test_dispatch_actions_integration.py asn_module/tests/integration/dispatch_flow.py
git commit -m "test(integration): migrate barcode flow fixtures to relational authoring model"
```

---

### Task 10: Update Property/Schema Coverage for Relational Invariants

**Files:**
- Modify: `asn_module/property_tests/test_barcode_flow_properties.py`
- Modify: `asn_module/barcode_flow/tests/test_schema.py`
- Modify: `asn_module/barcode_flow/tests/test_runtime.py`

- [ ] **Step 1: Add failing property checks for same-flow links and delete guards**

```python
@given(flow_graphs())
def test_transition_links_belong_to_same_flow(graph):
    t = graph.transition
    assert t.flow == t.source_node_doc.flow == t.target_node_doc.flow
```

- [ ] **Step 2: Run property + schema suites and verify failure**

Run:
```bash
HYPOTHESIS_PROFILE=ci bench --site dev.localhost run-tests --module asn_module.property_tests.test_barcode_flow_properties --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_schema --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_runtime --lightmode
```
Expected: FAIL before updates.

- [ ] **Step 3: Update tests to match relational contracts**

- [ ] **Step 4: Re-run suites**

Run: same commands as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/property_tests/test_barcode_flow_properties.py asn_module/barcode_flow/tests/test_schema.py asn_module/barcode_flow/tests/test_runtime.py
git commit -m "test(barcode-flow): enforce relational flow invariants in property and schema suites"
```

---

### Task 11: Documentation and End-to-End Verification Gate

**Files:**
- Modify: `docs/BarcodeFlowConfiguration.md`
- Modify: `docs/ProjectOverview.md`

- [ ] **Step 1: Update docs for relational setup and link picker behavior**

```markdown
1. Create Barcode Flow Definition + Scopes
2. Create Nodes/Conditions/Field Maps/QR Action Definitions
3. Create custom-handler bindings
4. Create transitions with flow-scoped link pickers
5. Optional node/transition event bindings
6. Hard-delete blocks on referenced records
```

- [ ] **Step 2: Run targeted suites (dependency order)**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_resolver --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_conditions --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_mapping --lightmode
bench --site dev.localhost run-tests --module asn_module.barcode_flow.tests.test_runtime --lightmode
bench --site dev.localhost run-tests --module asn_module.tests.integration.test_barcode_flow_integration --lightmode
HYPOTHESIS_PROFILE=ci bench --site dev.localhost run-tests --module asn_module.property_tests.test_barcode_flow_properties --lightmode
```
Expected: PASS.

- [ ] **Step 3: Run full app smoke + quality gate**

Run:
```bash
bench --site dev.localhost run-tests --app asn_module --lightmode
cd /workspace
pre-commit run --all-files
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/BarcodeFlowConfiguration.md docs/ProjectOverview.md
git commit -m "docs(barcode-flow): document relational link-field configuration workflow"
```

---

## Final Verification Checklist
- [ ] All new/modified doctypes load on migrate.
- [ ] Runtime no longer depends on embedded definition child tables for nodes/transitions/conditions/maps/bindings.
- [ ] Mode-driven validation contracts are enforced before runtime.
- [ ] Flow-scoped link picker filters are applied in transition and action-binding forms.
- [ ] Delete guards block all specified dependency edges with actionable identifiers.
- [ ] Resolver/dispatch/runtime tests, integration coverage, and full app smoke pass.
