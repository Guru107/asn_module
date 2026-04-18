# EDI 856 Baseline + Optional 855 Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic X12 4010 856 baseline compliance validation, and enforce optional 855 precondition gating with default bypass at supplier policy level (`Supplier.requires_855_ack=false`).

**Architecture:** Introduce a focused `edi_856` package that parses, validates, and reports baseline compliance with stable rule IDs. Integrate a small export/gate service into ASN flow: read `Supplier.requires_855_ack`; when false, 856 can proceed directly and ASN reference falls back to purchase order reference; when true, 856 requires a stored valid acknowledgment reference before export.

**Tech Stack:** Frappe v16 DocType JSON/Python, Python `FrappeTestCase`, existing ASN doctype/controller patterns, bench test runner.

---

## Decision and Trade-offs (Locked)

1. Compliance matrix + deterministic validator (selected)

Trade-off: More upfront implementation than inline checks, but auditable and repeatable for a 100% compliance claim.

1. Optional 855 gating via explicit Supplier-level flag (selected)

Trade-off: Simple, predictable operator control per supplier, but depends on correct supplier master data maintenance.

1. Auto-detect whether 855 is required (rejected for now)

Trade-off: Less manual setup, but introduces inference errors and harder troubleshooting.

Locked default:

- `Supplier.requires_855_ack = 0` (bypass by default).

UI copy requirement (mandatory):

- User-facing labels/messages must use business language, not raw EDI numeric codes.
- Keep EDI codes only in code, logs, and compliance docs.
- ASN reference must support both acknowledgment and purchase order fallback usage.

Cardinality requirement (mandatory):

- One ASN must map to exactly one purchase order.
- Multiple ASNs may map to the same purchase order.

## File Structure (locked before implementation)

- Create: `asn_module/edi_856/__init__.py`
- Create: `asn_module/edi_856/parser.py`
- Create: `asn_module/edi_856/rules_4010.py`
- Create: `asn_module/edi_856/validator.py`
- Create: `asn_module/edi_856/reporting.py`
- Create: `asn_module/edi_856/service.py`
- Create: `asn_module/edi_856/tests/__init__.py`
- Create: `asn_module/edi_856/tests/test_parser.py`
- Create: `asn_module/edi_856/tests/test_validator.py`
- Create: `asn_module/edi_856/tests/test_service.py`
- Create: `asn_module/edi_856/tests/fixtures/valid_856_minimal.txt`
- Create: `asn_module/edi_856/tests/fixtures/invalid_missing_bsn.txt`
- Create: `asn_module/custom_fields/supplier.py`
- Modify: `asn_module/setup.py`
- Modify: `asn_module/asn_module/doctype/asn/asn.json`
- Modify: `asn_module/asn_module/doctype/asn/asn.py`
- Modify: `asn_module/asn_module/doctype/asn/test_asn.py`
- Create: `docs/edi/856-baseline-compliance-matrix.md`
- Modify: `docs/superpowers/specs/2026-04-17-edi-856-baseline-compliance-design.md` (only if tiny clarifications are needed after implementation reality checks)

### Task 1: Add Supplier-Level Optional 855 Configuration Field

**Files:**

- Create: `asn_module/custom_fields/supplier.py`
- Modify: `asn_module/setup.py`
- Modify: `asn_module/asn_module/doctype/asn/asn.json`
- Test: `asn_module/asn_module/doctype/asn/test_asn.py`
- **Step 1: Write failing doctype/controller tests for new fields and defaults**

```python
def test_supplier_requires_855_ack_defaults_to_false(self):
    supplier = frappe.get_doc("Supplier", _ensure_supplier())
    self.assertEqual(int(getattr(supplier, "requires_855_ack", 0) or 0), 0)

def test_asn_rejects_multiple_purchase_orders(self):
    po1 = create_purchase_order(do_not_submit=True)
    po2 = create_purchase_order(do_not_submit=True)
    asn = make_test_asn(purchase_order=po1)
    asn.items[0].purchase_order = po1.name
    asn.items[0].purchase_order_item = po1.items[0].name
    asn.append("items", {
        "purchase_order": po2.name,
        "purchase_order_item": po2.items[0].name,
        "item_code": po2.items[0].item_code,
        "qty": 1,
        "uom": po2.items[0].uom,
        "rate": po2.items[0].rate,
    })
    with self.assertRaises(frappe.ValidationError):
        asn.insert(ignore_permissions=True)
```

- **Step 2: Run ASN tests to confirm failure on missing field behavior**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn --lightmode`  
Expected: FAIL due to missing `Supplier.requires_855_ack` custom field assertion.

- **Step 3: Add Supplier custom field setup and wire it in after-install**

```python
# asn_module/custom_fields/supplier.py
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def setup():
    create_custom_fields({
        "Supplier": [
            {
                "fieldname": "requires_855_ack",
                "fieldtype": "Check",
                "label": "Require purchase order acknowledgment before shipment notice",
                "default": "0",
                "insert_after": "supplier_group",
            }
        ]
    })
```

```python
# asn_module/setup.py
from asn_module.custom_fields.supplier import setup as setup_supplier_fields

def after_install():
    setup_supplier_fields()
    ...
```

```json
{
  "fieldname": "ack_855_reference",
  "fieldtype": "Data",
  "label": "Acknowledgment or purchase order reference",
  "depends_on": "eval:doc.supplier"
}
```

```python
# asn_module/asn_module/doctype/asn/asn.py
def _validate_single_purchase_order(self):
    po_values = {
        (row.purchase_order or "").strip()
        for row in (self.items or [])
        if (row.purchase_order or "").strip()
    }
    if len(po_values) <= 1:
        return
    frappe.throw("One shipment notice can reference only one purchase order.")
```

- **Step 4: Re-run ASN tests and verify pass for default behavior**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn --lightmode`  
Expected: PASS for new default test; existing tests remain green.

- **Step 5: Commit**

```bash
git add asn_module/custom_fields/supplier.py asn_module/setup.py asn_module/asn_module/doctype/asn/asn.json asn_module/asn_module/doctype/asn/test_asn.py
git commit -m "feat(supplier): add optional 855 gate policy field with bypass default"
```

### Task 2: Build 856 Parser and Rule Catalog (4010 Baseline)

**Files:**

- Create: `asn_module/edi_856/parser.py`
- Create: `asn_module/edi_856/rules_4010.py`
- Create: `asn_module/edi_856/tests/test_parser.py`
- Create: `asn_module/edi_856/tests/fixtures/valid_856_minimal.txt`
- **Step 1: Write failing parser tests for separators and segment tokenization**

```python
def test_parse_edi_segments_with_default_separators(self):
    text = "ST*856*0001~BSN*00*SHIP1*20260417*1230~SE*3*0001~"
    parsed = parse_edi(text)
    self.assertEqual([s.tag for s in parsed.segments], ["ST", "BSN", "SE"])
```

- **Step 2: Run parser tests and confirm failure**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_parser --lightmode`  
Expected: FAIL because parser module is not implemented.

- **Step 3: Implement minimal parser contract and baseline rule skeleton**

```python
@dataclass(frozen=True)
class Segment:
    tag: str
    elements: tuple[str, ...]
    index: int

@dataclass(frozen=True)
class ParsedEdi:
    segments: tuple[Segment, ...]

REQUIRED_SEGMENTS = ("ST", "BSN", "HL", "CTT", "SE")
```

- **Step 4: Re-run parser tests**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_parser --lightmode`  
Expected: PASS.

- **Step 5: Commit**

```bash
git add asn_module/edi_856/parser.py asn_module/edi_856/rules_4010.py asn_module/edi_856/tests/test_parser.py asn_module/edi_856/tests/fixtures/valid_856_minimal.txt
git commit -m "feat(edi-856): add parser primitives and baseline rule catalog skeleton"
```

### Task 3: Implement Deterministic 856 Baseline Validator

**Files:**

- Create: `asn_module/edi_856/validator.py`
- Create: `asn_module/edi_856/reporting.py`
- Create: `asn_module/edi_856/tests/test_validator.py`
- Create: `asn_module/edi_856/tests/fixtures/invalid_missing_bsn.txt`
- **Step 1: Write failing validator tests for required segment/order/control checks**

```python
def test_validator_flags_missing_bsn_rule_id(self):
    result = validate_856_baseline(load_fixture("invalid_missing_bsn.txt"))
    assert not result.is_compliant
    assert any(f.rule_id == "SEG-BSN-REQ-001" for f in result.errors)

def test_validator_enforces_st_se_control_match(self):
    result = validate_856_baseline("ST*856*0001~BSN*00*X*20260417*1200~SE*3*0002~")
    assert any(f.rule_id == "CNT-SE02-ST02-MATCH-001" for f in result.errors)
```

- **Step 2: Run validator tests to confirm failure first**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_validator --lightmode`  
Expected: FAIL on missing validator implementation.

- **Step 3: Implement validator and reporting contract with stable `rule_id`s**

```python
@dataclass(frozen=True)
class ComplianceFinding:
    rule_id: str
    severity: str
    message: str
    segment_tag: str | None
    segment_index: int | None
    element_index: int | None
    fix_hint: str | None

@dataclass
class ComplianceResult:
    is_compliant: bool
    errors: list[ComplianceFinding]
    warnings: list[ComplianceFinding]
    computed_metrics: dict[str, int]
```

- **Step 4: Re-run validator tests and ensure deterministic rule-id assertions pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_validator --lightmode`  
Expected: PASS.

- **Step 5: Commit**

```bash
git add asn_module/edi_856/validator.py asn_module/edi_856/reporting.py asn_module/edi_856/tests/test_validator.py asn_module/edi_856/tests/fixtures/invalid_missing_bsn.txt
git commit -m "feat(edi-856): add baseline validator and rule-id based findings"
```

### Task 4: Add Optional 855 Gate and 856 Export Service Integration

**Files:**

- Create: `asn_module/edi_856/service.py`
- Modify: `asn_module/asn_module/doctype/asn/asn.py`
- Create: `asn_module/edi_856/tests/test_service.py`
- Modify: `asn_module/asn_module/doctype/asn/test_asn.py`
- **Step 1: Write failing service tests for default bypass and enforced gate paths**

```python
def test_export_856_allows_bypass_when_requires_855_false(self):
    asn = make_test_asn()
    frappe.db.set_value("Supplier", asn.supplier, "requires_855_ack", 0, update_modified=False)
    asn.ack_855_reference = ""
    asn.save(ignore_permissions=True)
    payload = export_856_for_asn(asn.name)
    self.assertIn("ST*856*", payload)
    refreshed = frappe.get_doc("ASN", asn.name)
    self.assertTrue((refreshed.ack_855_reference or "").strip())

def test_export_856_blocks_when_requires_855_true_and_reference_missing(self):
    asn = make_test_asn()
    frappe.db.set_value("Supplier", asn.supplier, "requires_855_ack", 1, update_modified=False)
    asn.ack_855_reference = ""
    with self.assertRaises(frappe.ValidationError):
        export_856_for_asn(asn.name)
```

- **Step 2: Run service tests to confirm failure**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_service --lightmode`  
Expected: FAIL because export service/gate does not exist.

- **Step 3: Implement gate and export integration**

```python
def _derive_purchase_order_reference(asn_doc):
    for row in (asn_doc.items or []):
        value = (row.purchase_order or "").strip()
        if value:
            return value
    return ""

def assert_855_gate(asn_doc):
    supplier_requires_ack = int(
        frappe.db.get_value("Supplier", asn_doc.supplier, "requires_855_ack") or 0
    )
    if supplier_requires_ack != 1:
        fallback_ref = _derive_purchase_order_reference(asn_doc)
        if fallback_ref and not (asn_doc.ack_855_reference or "").strip():
            frappe.db.set_value("ASN", asn_doc.name, "ack_855_reference", fallback_ref, update_modified=False)
        return
    if not (asn_doc.ack_855_reference or "").strip():
        frappe.throw("Purchase order acknowledgment is required before sending shipment notice.")
```

```python
@frappe.whitelist()
def export_edi_856(asn_name: str) -> dict:
    return export_856_for_asn(asn_name)
```

- **Step 4: Re-run ASN + service tests**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_service --lightmode
bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn --lightmode
```

Expected: PASS for both modules.

- **Step 5: Commit**

```bash
git add asn_module/edi_856/service.py asn_module/asn_module/doctype/asn/asn.py asn_module/edi_856/tests/test_service.py asn_module/asn_module/doctype/asn/test_asn.py
git commit -m "feat(edi-856): enforce optional 855 precondition gate on 856 export"
```

### Task 5: Create Compliance Matrix Artifact and Wire Verification Commands

**Files:**

- Create: `docs/edi/856-baseline-compliance-matrix.md`
- Modify: `README.md` (if needed for operator-facing commands)
- **Step 1: Write matrix doc with rule IDs, descriptions, and test references**

```markdown
| Rule ID | Rule | Test |
|---|---|---|
| SEG-BSN-REQ-001 | BSN segment required once | asn_module/edi_856/tests/test_validator.py::test_validator_flags_missing_bsn_rule_id |
```

- **Step 2: Run full new EDI-856 test package**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_parser --lightmode
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_validator --lightmode
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_service --lightmode
```

Expected: PASS.

- **Step 3: Run lint and formatting checks**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/asn_module
ruff check asn_module/
npx eslint asn_module/ --quiet
```

Expected: PASS.

- **Step 4: Commit**

```bash
git add docs/edi/856-baseline-compliance-matrix.md README.md
git commit -m "docs(edi-856): add baseline compliance matrix and verification commands"
```

### Task 6: End-to-End Verification Gate

**Files:**

- Verification-only task.
- **Step 1: Run targeted regression suite around ASN and EDI-856**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --module asn_module.asn_module.doctype.asn.test_asn --lightmode
bench --site frappe16.localhost run-tests --module asn_module.tests.test_e2e_flow --lightmode
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_parser --lightmode
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_validator --lightmode
bench --site frappe16.localhost run-tests --module asn_module.edi_856.tests.test_service --lightmode
```

Expected: PASS.

- **Step 2: Final pre-commit gate**

Run: `cd /Users/gurudattkulkarni/Workspace/asn_module && pre-commit run --all-files`  
Expected: PASS.

- **Step 3: Final implementation commit**

```bash
git add -A
git commit -m "feat(edi-856): deliver baseline compliance validator with optional 855 gate"
```

## Notes for Implementers

- Keep 856 baseline checks and 855 gate logic separate; do not make 856 validity depend on partner-specific logic in this phase.
- Keep `Supplier.requires_855_ack` default at `0` to preserve bypass behavior unless explicitly enabled.
- Every validation failure must map to stable `rule_id` values so compliance matrix stays deterministic.
- Prefer explicit error messages over implicit silent fallback when 855 is required but missing.
- Keep all user-visible labels and errors in plain business language (no raw `850/855/856/810` code references).
- When acknowledgment is not required, always populate ASN reference from purchase order data deterministically.
- Enforce one-ASN-one-PO validation before reference derivation, so fallback never handles mixed PO sets.

