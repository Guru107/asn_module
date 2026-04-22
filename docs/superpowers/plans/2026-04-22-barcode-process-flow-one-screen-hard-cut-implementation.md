# Barcode Process Flow One-Screen Hard-Cut Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing multi-doctype barcode-flow graph with a one-screen `Barcode Process Flow` model, support ERPNext v15/v16 via capability filtering, and remove all obsolete graph code/tests.

**Architecture:** Introduce a new `barcode_process_flow` runtime package driven by `Barcode Process Flow` + `Flow Step` rows, `Barcode Rule`, and `Barcode Mapping Set`. Dispatch resolves eligible steps directly by source doctype and context, executes mapping or server-script mode, and logs deterministic outcomes. Old `barcode_flow` graph doctypes/runtime/tests are removed in a hard cut.

**Tech Stack:** Frappe/ERPNext (v15 + v16), Python 3, DocType JSON + controllers, JS doctype scripts, pytest/FrappeTestCase, Hypothesis property tests.

---

## File Structure

### New files/directories

- `asn_module/asn_module/doctype/barcode_process_flow/`
- `asn_module/asn_module/doctype/flow_step/`
- `asn_module/asn_module/doctype/barcode_rule/`
- `asn_module/asn_module/doctype/barcode_mapping_set/`
- `asn_module/asn_module/doctype/barcode_mapping_row/`
- `asn_module/asn_module/doctype/barcode_handler_template/` (or code-defined catalog helper if no doctype)
- `asn_module/barcode_process_flow/__init__.py`
- `asn_module/barcode_process_flow/capabilities.py`
- `asn_module/barcode_process_flow/repository.py`
- `asn_module/barcode_process_flow/rules.py`
- `asn_module/barcode_process_flow/mapping.py`
- `asn_module/barcode_process_flow/runtime.py`
- `asn_module/barcode_process_flow/tests/test_capabilities.py`
- `asn_module/barcode_process_flow/tests/test_repository.py`
- `asn_module/barcode_process_flow/tests/test_rules.py`
- `asn_module/barcode_process_flow/tests/test_mapping.py`
- `asn_module/barcode_process_flow/tests/test_runtime.py`
- `asn_module/tests/integration/test_barcode_process_flow_integration.py`
- `asn_module/property_tests/test_barcode_process_flow_properties.py`

### Existing files to modify

- `asn_module/hooks.py`
- `asn_module/qr_engine/dispatch.py`
- `asn_module/qr_engine/generate.py`
- `asn_module/qr_engine/tests/test_dispatch.py`
- `asn_module/qr_engine/tests/test_dispatch_errors.py`
- `asn_module/setup.py`
- `asn_module/setup_actions.py`
- `asn_module/commands.py`
- `asn_module/patches.txt`
- `docs/BarcodeFlowConfiguration.md`
- `docs/BarcodeFlowUserWiki.md`
- `docs/ProjectOverview.md`

### Existing files to delete (hard cut)

- `asn_module/barcode_flow/*`
- `asn_module/public/js/doctype/barcode_flow_transition.js`
- `asn_module/public/js/doctype/barcode_flow_action_binding.js`
- `asn_module/asn_module/doctype/barcode_flow_definition/*`
- `asn_module/asn_module/doctype/barcode_flow_scope/*`
- `asn_module/asn_module/doctype/barcode_flow_node/*`
- `asn_module/asn_module/doctype/barcode_flow_transition/*`
- `asn_module/asn_module/doctype/barcode_flow_action_binding/*`
- `asn_module/asn_module/doctype/barcode_flow_condition/*`
- `asn_module/asn_module/doctype/barcode_flow_field_map/*`
- `asn_module/asn_module/doctype/qr_action_registry/*`
- `asn_module/asn_module/doctype/qr_action_registry_item/*`
- `asn_module/asn_module/doctype/qr_action_definition/*`
- `asn_module/property_tests/test_barcode_flow_properties.py`
- `asn_module/tests/integration/test_barcode_flow_integration.py`
- `asn_module/tests/integration/dispatch_flow.py`
- `asn_module/patches/post_model_sync/2026_04_21_add_barcode_flow_indexes.py`

## Chunk 1: Schema Hard Cut and One-Screen Model

### Task 1: Introduce new one-screen doctypes (header + rows + rules + mapping)

**Files:**
- Create: `asn_module/asn_module/doctype/barcode_process_flow/*`
- Create: `asn_module/asn_module/doctype/flow_step/*`
- Create: `asn_module/asn_module/doctype/barcode_rule/*`
- Create: `asn_module/asn_module/doctype/barcode_mapping_set/*`
- Create: `asn_module/asn_module/doctype/barcode_mapping_row/*`
- Test: `asn_module/barcode_process_flow/tests/test_repository.py`

- [ ] **Step 1: Write failing repository/schema tests (@superpowers:test-driven-development)**

```python
# asn_module/barcode_process_flow/tests/test_repository.py

def test_flow_step_requires_from_to_doctype(flow_factory):
    flow = flow_factory()
    step = flow.append("steps", {"from_doctype": "ASN"})
    with pytest.raises(frappe.ValidationError):
        flow.save()
```

- [ ] **Step 2: Run failing tests**

Run:
```bash
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_repository --lightmode
```
Expected: FAIL due to missing doctypes/constraints.

- [ ] **Step 3: Implement minimal doctypes and validation controllers**

```python
# barcode_process_flow.py
class BarcodeProcessFlow(Document):
    def validate(self):
        if not self.flow_name:
            frappe.throw("Flow Name is required")
```

```python
# flow_step.py
class FlowStep(Document):
    def validate(self):
        if not self.from_doctype or not self.to_doctype:
            frappe.throw("From DocType and To DocType are required")
```

- [ ] **Step 4: Re-run tests to pass**

Run same module; expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/barcode_process_flow asn_module/asn_module/doctype/flow_step asn_module/asn_module/doctype/barcode_rule asn_module/asn_module/doctype/barcode_mapping_set asn_module/asn_module/doctype/barcode_mapping_row asn_module/barcode_process_flow/tests/test_repository.py
git commit -m "feat(flow): add one-screen barcode process flow doctypes"
```

### Task 2: Remove obsolete graph doctypes and doctype JS hooks

**Files:**
- Modify: `asn_module/hooks.py`
- Delete: old doctypes listed in File Structure
- Delete: `asn_module/public/js/doctype/barcode_flow_transition.js`
- Delete: `asn_module/public/js/doctype/barcode_flow_action_binding.js`
- Test: `asn_module/barcode_process_flow/tests/test_repository.py`

- [ ] **Step 1: Add failing test that old doctypes are no longer required**

```python
def test_new_flow_does_not_require_legacy_graph_doctypes():
    assert frappe.db.exists("DocType", "Barcode Process Flow")
    assert not frappe.db.exists("DocType", "Barcode Flow Transition")
```

- [ ] **Step 2: Run test to verify failure before deletion**

Run same module; expected: FAIL because old doctype still exists.

- [ ] **Step 3: Remove old doctypes and hook references**

Commands:
```bash
git rm -r asn_module/asn_module/doctype/barcode_flow_definition asn_module/asn_module/doctype/barcode_flow_scope asn_module/asn_module/doctype/barcode_flow_node asn_module/asn_module/doctype/barcode_flow_transition asn_module/asn_module/doctype/barcode_flow_action_binding asn_module/asn_module/doctype/barcode_flow_condition asn_module/asn_module/doctype/barcode_flow_field_map

git rm asn_module/public/js/doctype/barcode_flow_transition.js asn_module/public/js/doctype/barcode_flow_action_binding.js
```

And update `hooks.py`:

```python
doctype_js = {}
```

- [ ] **Step 4: Re-run tests and `bench migrate` smoke**

Run:
```bash
bench --site frappe16.localhost migrate
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_repository --lightmode
```
Expected: migrate success, tests PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/hooks.py
git commit -m "refactor(flow): remove legacy barcode-flow graph doctypes and hooks"
```

## Chunk 2: Runtime Replacement

### Task 3: Build capability matrix (v15/v16) and standard handler catalog

**Files:**
- Create: `asn_module/barcode_process_flow/capabilities.py`
- Modify: `asn_module/setup_actions.py`
- Delete: `asn_module/asn_module/doctype/qr_action_registry/*`
- Delete: `asn_module/asn_module/doctype/qr_action_registry_item/*`
- Delete: `asn_module/asn_module/doctype/qr_action_definition/*`
- Test: `asn_module/barcode_process_flow/tests/test_capabilities.py`

- [ ] **Step 1: Write failing capabilities tests**

```python
def test_mr_subcontracting_action_hidden_in_v15(monkeypatch):
    monkeypatch.setattr(capabilities, "get_erp_major", lambda: 15)
    supported = capabilities.get_supported_pairs("Material Request")
    assert ("Material Request", "Purchase Order", "mr_subcontracting_to_po") not in supported
```

- [ ] **Step 2: Run failing test**

```bash
bench --site development.localhost run-tests --module asn_module.barcode_process_flow.tests.test_capabilities --lightmode
```
Expected: FAIL until matrix implemented.

- [ ] **Step 3: Implement matrix + provider resolution**

```python
# capabilities.py
CAPABILITIES = {
    "mr_purchase_to_po": {"min": 15, "max": 16},
    "mr_subcontracting_to_po": {"min": 16, "max": 16},
}
```

- [ ] **Step 4: Remove QR registry doctypes and old setup projection**

- delete registry doctypes via `git rm -r ...`
- replace `setup_actions.py` with capability bootstrap helpers only.

- [ ] **Step 5: Re-run v15 + v16 capability tests**

```bash
bench --site development.localhost run-tests --module asn_module.barcode_process_flow.tests.test_capabilities --lightmode
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_capabilities --lightmode
```
Expected: PASS on both.

- [ ] **Step 6: Commit**

```bash
git add asn_module/barcode_process_flow/capabilities.py asn_module/setup_actions.py
git commit -m "feat(flow): add v15/v16 capability matrix and remove qr registry model"
```

### Task 4: Replace dispatch to resolve `Flow Step` rows directly

**Files:**
- Create: `asn_module/barcode_process_flow/repository.py`
- Create: `asn_module/barcode_process_flow/runtime.py`
- Modify: `asn_module/qr_engine/dispatch.py`
- Modify: `asn_module/qr_engine/generate.py`
- Test: `asn_module/barcode_process_flow/tests/test_runtime.py`
- Test: `asn_module/qr_engine/tests/test_dispatch.py`

- [ ] **Step 1: Write failing runtime tests for step selection + priority**

```python
def test_runtime_picks_highest_priority_eligible_step(flow_fixture):
    contract = runtime.dispatch_from_scan(flow_fixture.scan_code)
    assert contract["step_label"] == "PR to PI"
```

- [ ] **Step 2: Run runtime tests to fail**

```bash
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_runtime --lightmode
```

- [ ] **Step 3: Implement repository query and runtime execution**

```python
# repository.py

def get_active_steps_for_source(source_doctype, context):
    return frappe.get_all("Flow Step", filters={"from_doctype": source_doctype, "is_active": 1}, fields=[...])
```

```python
# runtime.py

def execute_step(step, source_doc):
    if step.execution_mode == "Mapping":
        return execute_mapping_step(step, source_doc)
    return execute_server_script_step(step, source_doc)
```

- [ ] **Step 4: Update dispatch to use new runtime and flow-step token metadata**

```python
# dispatch.py
flow_steps = repository.get_active_steps_for_source(source_doc.doctype, context)
winning_steps = runtime.resolve_eligible_steps(flow_steps, source_doc)
```

- [ ] **Step 5: Re-run dispatch + runtime tests**

```bash
bench --site frappe16.localhost run-tests --module asn_module.qr_engine.tests.test_dispatch --lightmode
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_runtime --lightmode
```

- [ ] **Step 6: Commit**

```bash
git add asn_module/qr_engine/dispatch.py asn_module/qr_engine/generate.py asn_module/barcode_process_flow/repository.py asn_module/barcode_process_flow/runtime.py asn_module/barcode_process_flow/tests/test_runtime.py
git commit -m "refactor(dispatch): execute barcode process flow steps directly"
```

## Chunk 3: Rules + Mapping + Material Request/Subcontracting Coverage

### Task 5: Implement new rule evaluator (`Barcode Rule`) with item/aggregate semantics

**Files:**
- Create: `asn_module/barcode_process_flow/rules.py`
- Test: `asn_module/barcode_process_flow/tests/test_rules.py`

- [ ] **Step 1: Write failing tests for `items_any` and `items_aggregate`**

```python
def test_items_any_rule_true_when_any_item_matches():
    assert evaluate_rule(doc, rule_items_any) is True
```

- [ ] **Step 2: Run test to fail**

```bash
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_rules --lightmode
```

- [ ] **Step 3: Implement minimal evaluator and operators**

```python
ALLOWED_SCOPES = {"header", "items_any", "items_all", "items_aggregate"}
```

- [ ] **Step 4: Re-run rules tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_process_flow/rules.py asn_module/barcode_process_flow/tests/test_rules.py
git commit -m "feat(flow): add barcode rule evaluator for header/item/aggregate conditions"
```

### Task 6: Implement picker-driven mapping set execution (header + item)

**Files:**
- Create: `asn_module/barcode_process_flow/mapping.py`
- Test: `asn_module/barcode_process_flow/tests/test_mapping.py`

- [ ] **Step 1: Write failing mapping tests for header and item row mapping**

```python
def test_mapping_set_copies_item_rows_from_asn_to_pr():
    pr_doc = build_target_from_mapping(asn_doc, mapping_set)
    assert len(pr_doc.items) == len(asn_doc.items)
```

- [ ] **Step 2: Run test to fail**

```bash
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_mapping --lightmode
```

- [ ] **Step 3: Implement mapping builder + link traversal resolvers**

```python
def resolve_source_selector(doc, selector):
    # selector tokenized from picker metadata, not free-form dotted input
    ...
```

- [ ] **Step 4: Re-run mapping tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_process_flow/mapping.py asn_module/barcode_process_flow/tests/test_mapping.py
git commit -m "feat(flow): add picker-driven mapping set execution"
```

### Task 7: Add standard handler adapters for MR + subcontracting + outbound

**Files:**
- Modify: `asn_module/handlers/*` (reuse existing where possible)
- Create: `asn_module/barcode_process_flow/handlers.py` (thin adapter layer)
- Test: `asn_module/tests/integration/test_barcode_process_flow_integration.py`

- [ ] **Step 1: Write failing integration tests for key standard pairs**

```python
def test_mr_purchase_to_po_available_and_executes():
    ...

def test_asn_to_subcontracting_receipt_requires_subcontracting_context():
    with pytest.raises(frappe.ValidationError):
        dispatch(...)
```

- [ ] **Step 2: Run integration tests to fail**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.integration.test_barcode_process_flow_integration --lightmode
```

- [ ] **Step 3: Implement adapter registry to existing ERPNext/native maker methods**

```python
STANDARD_HANDLERS = {
    "mr_purchase_to_po": "erpnext.stock.doctype.material_request.material_request.make_purchase_order",
    "sco_to_scr": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
}
```

- [ ] **Step 4: Re-run integration tests on v16 + critical subset on v15**

```bash
bench --site frappe16.localhost run-tests --module asn_module.tests.integration.test_barcode_process_flow_integration --lightmode
bench --site development.localhost run-tests --module asn_module.tests.integration.test_barcode_process_flow_integration --lightmode
```

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_process_flow/handlers.py asn_module/tests/integration/test_barcode_process_flow_integration.py
git commit -m "feat(flow): add standard handler adapters for mr subcontracting and outbound paths"
```

## Chunk 4: Remove Obsolete Runtime/Test Surface and Final Verification

### Task 8: Remove old barcode-flow runtime modules and dependent tests

**Files:**
- Delete: `asn_module/barcode_flow/*`
- Delete: `asn_module/barcode_flow/tests/*`
- Delete: `asn_module/property_tests/test_barcode_flow_properties.py`
- Delete: `asn_module/tests/integration/test_barcode_flow_integration.py`
- Delete: `asn_module/tests/integration/dispatch_flow.py`
- Modify: `asn_module/patches.txt`
- Delete: `asn_module/patches/post_model_sync/2026_04_21_add_barcode_flow_indexes.py`

- [ ] **Step 1: Write guard test to assert old module import fails**

```python
def test_legacy_barcode_flow_module_removed():
    with pytest.raises(ModuleNotFoundError):
        __import__("asn_module.barcode_flow.runtime")
```

- [ ] **Step 2: Run guard test to fail pre-removal**

Expected: FAIL (module still exists).

- [ ] **Step 3: Remove old modules/tests via `git rm` and patch references**

- delete files
- remove old patch reference from `patches.txt`

- [ ] **Step 4: Re-run targeted suites**

```bash
bench --site frappe16.localhost run-tests --module asn_module.barcode_process_flow.tests.test_runtime --lightmode
bench --site frappe16.localhost run-tests --module asn_module.qr_engine.tests.test_dispatch --lightmode
HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests --module asn_module.property_tests.test_barcode_process_flow_properties --lightmode
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/patches.txt
git commit -m "chore(flow): remove legacy barcode-flow runtime modules tests and patches"
```

### Task 9: Update docs to one-screen model and remove legacy runbooks

**Files:**
- Modify: `docs/BarcodeFlowConfiguration.md`
- Modify: `docs/BarcodeFlowUserWiki.md`
- Modify: `docs/ProjectOverview.md`
- Modify: `docs/ProjectOverview.md` barcode verification commands section

- [ ] **Step 1: Skip doc assertion test (no doc-lint harness currently wired)**

- [ ] **Step 2: Update docs for hard-cut model and new doctypes/runtime**

Include:
- one-screen setup steps
- MR/subcontracting/outbound examples
- v15/v16 compatibility expectations
- removal of old graph authoring instructions

- [ ] **Step 3: Run linters/tests impacted by docs links and commands**

```bash
ruff check asn_module/
npx eslint asn_module/ --quiet
```

- [ ] **Step 4: Commit**

```bash
git add docs/BarcodeFlowConfiguration.md docs/BarcodeFlowUserWiki.md docs/ProjectOverview.md
git commit -m "docs(flow): switch runbooks to one-screen barcode process flow model"
```

### Task 10: Full regression matrix and PR readiness

**Files:**
- Modify: any residual fixes from verification only
- Test: full targeted matrix

- [ ] **Step 1: Execute full test matrix on v16**

```bash
bench --site frappe16.localhost run-tests --app asn_module --lightmode
```
Expected: PASS.

- [ ] **Step 2: Execute compatibility matrix on v15**

```bash
bench --site development.localhost run-tests --app asn_module --lightmode
```
Expected: PASS (or documented known unrelated upstream issues).

- [ ] **Step 3: Sanity check scan dispatch manually on both benches**

- configure one simple `ASN -> PR` step
- scan a generated barcode
- verify Scan Log records flow + step

- [ ] **Step 4: Final cleanup and commit**

```bash
git add -A
git commit -m "test(flow): validate one-screen runtime on v15 and v16"
```

- [ ] **Step 5: Open/update PR with migration note**

PR must clearly call out:
- hard cut (legacy model removed)
- no migration of old flow records
- required one-screen reconfiguration

## Reviewer Checklist (manual self-review in this harness)

- [ ] No references remain to old `barcode_flow` runtime package
- [ ] No references remain to `QR Action Registry` / `QR Action Definition` doctypes
- [ ] `hooks.py` has no removed doctype JS entries
- [ ] Dispatch path executes only new runtime
- [ ] v15 hides v16-only options
- [ ] Docs consistently describe one-screen model

## Execution Notes

- Prefer @superpowers:test-driven-development for each task.
- Use @superpowers:systematic-debugging for any failing dispatch edge case.
- Use frequent small commits exactly as listed.
