# Barcode Flow Configurability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable, context-scoped barcode flow engine so scans can create custom document paths (for example ASN -> Gate Pass -> PR -> PI/Stock Transfer) without hardcoded route logic.

**Architecture:** Keep `Scan Code`, `Scan Log`, and `dispatch` as the execution entrypoint, and add a declarative `Barcode Flow *` configuration model (definition, scope, nodes, transitions, conditions, mappings, action bindings). Dispatch resolves a unique scoped flow + transition, executes mapping/handler, then pre-generates or defers next scan codes based on transition mode (`immediate`, `runtime`, `hybrid`) with runtime re-validation.

**Tech Stack:** Frappe v16 DocTypes/hooks, Python services in `asn_module`, existing QR engine (`dispatch`, `generate_qr`, `scan_codes`), Frappe tests (`run-tests --lightmode`), Ruff/Eslint.

---

## Scope Check (Locked)

This is one cohesive subsystem (config-driven scan routing) rather than multiple independent projects. It is safe to implement as one phased plan with isolated tasks.

## Decision and Trade-offs (Locked)

1. Declarative graph + scoped resolution (selected)  
Trade-off: higher initial schema/runtime work, but predictable long-term configurability and low per-customer code branching.
2. Extend existing action registry JSON blobs (rejected)  
Trade-off: faster start but poor maintainability and validation surface.
3. Reuse ERPNext Workflow doctype semantics (rejected)  
Trade-off: familiar naming but weak fit for document-creation branching and barcode-generation semantics.

Additional locked decisions:

- No ERPNext `Workflow` naming collision: use `Barcode Flow *`.
- Default generation mode: `hybrid`.
- No auto-seeded legacy flow (project is pre-production).
- Ambiguous scope or transition match is a hard configuration error.

## File Structure (Locked Before Implementation)

Core schema:

- Create: `asn_module/asn_module/doctype/barcode_flow_definition/`
- Create: `asn_module/asn_module/doctype/barcode_flow_scope/`
- Create: `asn_module/asn_module/doctype/barcode_flow_node/`
- Create: `asn_module/asn_module/doctype/barcode_flow_transition/`
- Create: `asn_module/asn_module/doctype/barcode_flow_condition/`
- Create: `asn_module/asn_module/doctype/barcode_flow_field_map/`
- Create: `asn_module/asn_module/doctype/barcode_flow_action_binding/`

Runtime services:

- Create: `asn_module/barcode_flow/__init__.py`
- Create: `asn_module/barcode_flow/resolver.py`
- Create: `asn_module/barcode_flow/conditions.py`
- Create: `asn_module/barcode_flow/mapping.py`
- Create: `asn_module/barcode_flow/runtime.py`
- Create: `asn_module/barcode_flow/cache.py`
- Create: `asn_module/barcode_flow/errors.py`

Integration points:

- Modify: `asn_module/qr_engine/dispatch.py`
- Modify: `asn_module/qr_engine/generate.py`
- Modify: `asn_module/asn_module/doctype/scan_log/scan_log.json` (flow metadata fields)
- Modify: `asn_module/setup_actions.py` (validation compatibility only; no flow seeding)

Tests:

- Create: `asn_module/barcode_flow/tests/test_schema.py`
- Create: `asn_module/barcode_flow/tests/test_resolver.py`
- Create: `asn_module/barcode_flow/tests/test_conditions.py`
- Create: `asn_module/barcode_flow/tests/test_mapping.py`
- Create: `asn_module/barcode_flow/tests/test_runtime.py`
- Create: `asn_module/tests/integration/test_barcode_flow_integration.py`
- Create: `asn_module/property_tests/test_barcode_flow_properties.py`

Docs:

- Modify: `docs/ProjectOverview.md` (new configuration docs)
- Create: `docs/BarcodeFlowConfiguration.md`

### Task 1: Create `Barcode Flow *` DocType Schema

**Files:**
- Create: `asn_module/asn_module/doctype/barcode_flow_definition/barcode_flow_definition.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_definition/barcode_flow_definition.py`
- Create: `asn_module/asn_module/doctype/barcode_flow_scope/barcode_flow_scope.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_node/barcode_flow_node.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_transition/barcode_flow_transition.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_condition/barcode_flow_condition.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_field_map/barcode_flow_field_map.json`
- Create: `asn_module/asn_module/doctype/barcode_flow_action_binding/barcode_flow_action_binding.json`
- Create: `asn_module/barcode_flow/tests/test_schema.py`

- [ ] **Step 1: Write failing DocType validation tests for required fields and uniqueness**

```python
def test_barcode_flow_definition_requires_name(self):
	with self.assertRaises(frappe.ValidationError):
		frappe.get_doc({"doctype": "Barcode Flow Definition"}).insert(ignore_permissions=True)

def test_transition_key_unique_within_flow(self):
	flow = make_flow_definition("Inbound A")
	make_transition(flow, transition_key="PR_TO_PI")
	with self.assertRaises(frappe.UniqueValidationError):
		make_transition(flow, transition_key="PR_TO_PI")
```

- [ ] **Step 2: Run targeted tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_schema --lightmode
```
Expected: FAIL because DocTypes/validators do not exist yet.

- [ ] **Step 3: Create minimal DocTypes and parent validator**

```python
class BarcodeFlowDefinition(Document):
	def validate(self):
		if not self.flow_name:
			frappe.throw(_("Flow Name is required"))
```

- [ ] **Step 4: Re-run tests and ensure schema-level passes**

Run: same command as Step 2  
Expected: PASS for schema validation tests.

- [ ] **Step 5: Commit**

```bash
git add \
  asn_module/asn_module/doctype/barcode_flow_definition \
  asn_module/asn_module/doctype/barcode_flow_scope \
  asn_module/asn_module/doctype/barcode_flow_node \
  asn_module/asn_module/doctype/barcode_flow_transition \
  asn_module/asn_module/doctype/barcode_flow_condition \
  asn_module/asn_module/doctype/barcode_flow_field_map \
  asn_module/asn_module/doctype/barcode_flow_action_binding \
  asn_module/barcode_flow/tests/test_schema.py
git commit -m "feat(barcode-flow): add core configuration doctypes"
```

### Task 2: Build Scope Resolver with Deterministic Selection

**Files:**
- Create: `asn_module/barcode_flow/errors.py`
- Create: `asn_module/barcode_flow/resolver.py`
- Create: `asn_module/barcode_flow/tests/test_resolver.py`

- [ ] **Step 1: Write failing resolver tests for specificity, priority, and ambiguity**

```python
def test_scope_resolver_prefers_more_specific_scope(self):
	selected = resolve_flow(context={"company": "A", "warehouse": "WH-A"})
	self.assertEqual(selected.flow_name, "Flow-Company-Wh")

def test_scope_resolver_raises_on_ambiguous_match(self):
	with self.assertRaises(AmbiguousFlowScopeError):
		resolve_flow(context={"company": "A"})
```

- [ ] **Step 2: Run resolver tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_resolver --lightmode
```
Expected: FAIL because resolver is not implemented.

- [ ] **Step 3: Implement resolver and typed errors**

```python
def resolve_flow(context: dict) -> dict:
	matches = _get_scope_matches(context)
	if not matches:
		raise NoMatchingFlowError("No active Barcode Flow matches this context")
	winner = _select_single_match(matches)
	return winner
```

- [ ] **Step 4: Re-run resolver tests**

Run: same command as Step 2  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/errors.py asn_module/barcode_flow/resolver.py asn_module/barcode_flow/tests/test_resolver.py
git commit -m "feat(barcode-flow): add context-scoped flow resolver with ambiguity guards"
```

### Task 3: Implement Header + Item/Aggregate Condition Evaluator

**Files:**
- Create: `asn_module/barcode_flow/conditions.py`
- Create: `asn_module/barcode_flow/tests/test_conditions.py`

- [ ] **Step 1: Write failing tests for `header`, `items_any`, `items_all`, and aggregate built-ins**

```python
def test_items_any_true_when_one_item_matches(self):
	ok = evaluate_conditions(doc, [rule(scope="items_any", field_path="inspection_required_before_purchase", operator="=", value=True)])
	self.assertTrue(ok)

def test_items_aggregate_exists(self):
	ok = evaluate_conditions(doc, [rule(scope="items_aggregate", aggregate_fn="exists", field_path="inspection_required_before_purchase", operator="=", value=True)])
	self.assertTrue(ok)
```

- [ ] **Step 2: Run condition tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_conditions --lightmode
```
Expected: FAIL with missing evaluator behavior.

- [ ] **Step 3: Implement minimal evaluator with allowlisted operators**

```python
ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "contains", "is_set"}

def evaluate_conditions(doc, rules):
	return all(_evaluate_rule(doc, row) for row in rules if row.get("is_enabled", 1))
```

- [ ] **Step 4: Re-run condition tests**

Run: same command as Step 2  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/conditions.py asn_module/barcode_flow/tests/test_conditions.py
git commit -m "feat(barcode-flow): add header and item aggregate condition evaluator"
```

### Task 4: Implement Mapping Engine + Action Binding Runtime

**Files:**
- Create: `asn_module/barcode_flow/mapping.py`
- Create: `asn_module/barcode_flow/runtime.py`
- Create: `asn_module/barcode_flow/tests/test_mapping.py`
- Create: `asn_module/barcode_flow/tests/test_runtime.py`

- [ ] **Step 1: Write failing mapping/runtime tests for `mapping`, `custom_handler`, and `both`**

```python
def test_mapping_sets_constants_and_source_values(self):
	target = build_target_doc(source_doc, mappings)
	self.assertEqual(target.entry_type, "Gate In")
	self.assertEqual(target.supplier, source_doc.supplier)

def test_custom_handler_override_wins(self):
	result = execute_transition_binding(transition, source_doc)
	self.assertEqual(result["doctype"], "Gate Pass")
```

- [ ] **Step 2: Run mapping/runtime tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_mapping --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_runtime --lightmode
```
Expected: FAIL because binding engine is missing.

- [ ] **Step 3: Implement minimal binding execution**

```python
def execute_transition_binding(transition, source_doc):
	if transition.binding_mode == "custom_handler":
		return _call_custom_handler(transition.custom_handler, source_doc)
	target_doc = build_target_doc(source_doc, transition.field_maps)
	if transition.binding_mode == "both" and transition.handler_override_wins:
		return _call_custom_handler(transition.custom_handler, source_doc, prefilled=target_doc)
	target_doc.insert(ignore_permissions=True)
	return {"doctype": target_doc.doctype, "name": target_doc.name, "url": target_doc.get_url()}
```

- [ ] **Step 4: Re-run mapping/runtime tests**

Run: same commands as Step 2  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/mapping.py asn_module/barcode_flow/runtime.py asn_module/barcode_flow/tests/test_mapping.py asn_module/barcode_flow/tests/test_runtime.py
git commit -m "feat(barcode-flow): add transition field mapping and action binding runtime"
```

### Task 5: Integrate Dispatch with Flow Resolution and Transition Matching

**Files:**
- Modify: `asn_module/qr_engine/dispatch.py`
- Create: `asn_module/barcode_flow/cache.py`
- Modify: `asn_module/asn_module/doctype/scan_log/scan_log.json`
- Modify: `asn_module/asn_module/doctype/scan_log/scan_log.py`

- [ ] **Step 1: Write failing dispatch integration tests for no-flow, ambiguous-flow, and matched-flow**

```python
def test_dispatch_raises_when_no_flow_matches(self):
	with self.assertRaises(NoMatchingFlowError):
		dispatch(code=self.scan_code, device_info="integration")

def test_dispatch_records_flow_metadata_on_success(self):
	result = dispatch(code=self.scan_code, device_info="integration")
	log = frappe.get_last_doc("Scan Log")
	self.assertEqual(log.barcode_flow_definition, "Inbound Flow A")
	self.assertEqual(log.barcode_flow_transition, "ASN_TO_GATE_IN")
```

- [ ] **Step 2: Run dispatch tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch_errors --lightmode
```
Expected: FAIL on new flow-aware assertions.

- [ ] **Step 3: Wire flow resolution + transition execution into dispatch**

```python
flow = resolve_flow(context=_build_source_context(source_doctype, source_name))
transition = match_transition(flow, action_key=action_key, source_doctype=source_doctype, source_name=source_name)
handler_result = execute_transition_binding(transition, source_doc)
```

- [ ] **Step 4: Add scan-log metadata fields and include in insert**

```python
"barcode_flow_definition": flow.flow_name,
"barcode_flow_transition": transition.transition_key,
"scope_resolution_key": resolved_scope_key,
```

- [ ] **Step 5: Re-run dispatch suites**

Run: same commands as Step 2  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add asn_module/qr_engine/dispatch.py asn_module/barcode_flow/cache.py asn_module/asn_module/doctype/scan_log/scan_log.*
git commit -m "feat(dispatch): resolve and execute configurable barcode flow transitions"
```

### Task 6: Implement Hybrid Child Barcode Generation Pipeline

**Files:**
- Modify: `asn_module/barcode_flow/runtime.py`
- Modify: `asn_module/qr_engine/generate.py` (label helper extension)
- Modify: `asn_module/barcode_flow/tests/test_runtime.py`
- Create: `asn_module/tests/integration/test_barcode_flow_integration.py`

- [ ] **Step 1: Write failing tests for generation modes (`immediate`, `runtime`, `hybrid`)**

```python
def test_hybrid_generates_child_codes_but_revalidates_at_scan(self):
	result = execute_scan_transition(...)
	self.assertGreaterEqual(len(result["generated_scan_codes"]), 1)
```

- [ ] **Step 2: Run runtime + integration tests and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_runtime --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.integration.test_barcode_flow_integration --lightmode
```
Expected: FAIL on generation mode assertions.

- [ ] **Step 3: Implement child transition enumeration + code generation**

```python
def maybe_generate_child_codes(target_doc, transitions):
	for row in transitions:
		if row.generation_mode == "runtime":
			continue
		if row.generation_mode in {"immediate", "hybrid"} and evaluate_conditions(target_doc, row.conditions):
			get_or_create_scan_code(row.action_key, target_doc.doctype, target_doc.name)
```

- [ ] **Step 4: Re-run runtime + integration tests**

Run: same commands as Step 2  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/barcode_flow/runtime.py asn_module/qr_engine/generate.py asn_module/barcode_flow/tests/test_runtime.py asn_module/tests/integration/test_barcode_flow_integration.py
git commit -m "feat(barcode-flow): add hybrid child barcode generation with runtime revalidation"
```

### Task 7: Add Real-Flow Integration Coverage (Gate In, Direct PR, Outbound Gate Out)

**Files:**
- Modify: `asn_module/tests/integration/test_barcode_flow_integration.py`
- Modify: `asn_module/tests/integration/fixtures.py`

- [ ] **Step 1: Add failing integration cases for scoped flow selection**

```python
def test_asn_scan_routes_to_gate_pass_for_scoped_company(self):
	result = dispatch(code=asn_code_for_company_a, device_info="integration")
	self.assertEqual(result["doctype"], "Gate Pass")

def test_asn_scan_routes_direct_to_pr_when_gate_pass_scope_not_matched(self):
	result = dispatch(code=asn_code_for_company_b, device_info="integration")
	self.assertEqual(result["doctype"], "Purchase Receipt")
```

- [ ] **Step 2: Run integration module and confirm failure**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.integration.test_barcode_flow_integration --lightmode
```
Expected: FAIL before fixture/runtime completion.

- [ ] **Step 3: Implement missing fixture helpers and final wiring**

```python
def make_barcode_flow_with_scope(flow_name, company=None, warehouse=None, supplier_type=None):
	# create definition + scope + nodes + transitions for test setup
	return flow_name
```

- [ ] **Step 4: Re-run integration module**

Run: same command as Step 2  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add asn_module/tests/integration/test_barcode_flow_integration.py asn_module/tests/integration/fixtures.py
git commit -m "test(integration): cover scoped barcode flow routes and gate scenarios"
```

### Task 8: Property Tests for Ambiguity and Condition Edge Cases

**Files:**
- Create: `asn_module/property_tests/test_barcode_flow_properties.py`
- Modify: `asn_module/property_tests/property_suite.py`

- [ ] **Step 1: Add failing property tests for resolver determinism and condition boundaries**

```python
@given(scope_sets())
def test_scope_resolver_never_returns_multiple_winners(scope_set):
	result = try_resolve(scope_set)
	assert result.status in {"resolved", "no_match", "ambiguous_error"}

@given(item_collections())
def test_items_any_and_exists_equivalence(items):
	assert eval_items_any(items) == eval_exists(items)
```

- [ ] **Step 2: Run property module with CI profile and confirm baseline**

Run:
```bash
cd /home/ubuntu/frappe-bench
HYPOTHESIS_PROFILE=ci bench --site dev.localhost run-tests --app asn_module --module asn_module.property_tests.test_barcode_flow_properties --lightmode
```
Expected: FAIL until final evaluator/resolver edge handling is complete.

- [ ] **Step 3: Fix edge-handling gaps exposed by properties**

```python
if ambiguous_winners:
	raise AmbiguousFlowScopeError(...)
```

- [ ] **Step 4: Re-run property module with CI and local profiles**

Run:
```bash
cd /home/ubuntu/frappe-bench
HYPOTHESIS_PROFILE=ci bench --site dev.localhost run-tests --app asn_module --module asn_module.property_tests.test_barcode_flow_properties --lightmode
HYPOTHESIS_PROFILE=local bench --site dev.localhost run-tests --app asn_module --module asn_module.property_tests.test_barcode_flow_properties --lightmode
```
Expected: PASS on both profiles.

- [ ] **Step 5: Commit**

```bash
git add asn_module/property_tests/test_barcode_flow_properties.py asn_module/property_tests/property_suite.py
git commit -m "test(property): add barcode flow resolver and condition invariants"
```

### Task 9: Documentation and Operator Configuration Guide

**Files:**
- Create: `docs/BarcodeFlowConfiguration.md`
- Modify: `docs/ProjectOverview.md`

- [ ] **Step 1: Run baseline docs check before updates**

```bash
rg "Barcode Flow Definition" docs/ProjectOverview.md
```
Expected: not found before docs update.

- [ ] **Step 2: Add configuration runbook with concrete examples**

```markdown
Example A: ASN -> Gate Pass (Gate In) -> Purchase Receipt
Example B: ASN -> Purchase Receipt (no Gate Pass)
Example C: Dispatch -> Gate Pass (Gate Out) -> Mark Dispatched
```

- [ ] **Step 3: Run lint and formatting checks**

Run:
```bash
cd /Users/gurudattkulkarni/Workspace/asn_module
ruff check asn_module/
npx eslint asn_module/ --quiet
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/BarcodeFlowConfiguration.md docs/ProjectOverview.md
git commit -m "docs: add barcode flow configuration and operations guide"
```

### Task 10: Final Verification and Release Readiness

**Files:**
- No new files (verification task).

- [ ] **Step 1: Run targeted Python suites in dependency order**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_resolver --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_conditions --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_mapping --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.barcode_flow.tests.test_runtime --lightmode
bench --site dev.localhost run-tests --app asn_module --module asn_module.tests.integration.test_barcode_flow_integration --lightmode
HYPOTHESIS_PROFILE=ci bench --site dev.localhost run-tests --app asn_module --module asn_module.property_tests.test_barcode_flow_properties --lightmode
```
Expected: all PASS.

- [ ] **Step 2: Run full app smoke suite**

Run:
```bash
cd /home/ubuntu/frappe-bench
bench --site dev.localhost run-tests --app asn_module --lightmode
```
Expected: PASS for app tests.

- [ ] **Step 3: Run repository quality gate**

Run:
```bash
cd /Users/gurudattkulkarni/Workspace/asn_module
pre-commit run --all-files
```
Expected: PASS.

- [ ] **Step 4: Commit verification adjustments (if any)**

```bash
git add -A
git commit -m "chore: finalize barcode flow configurability verification fixes"
```
