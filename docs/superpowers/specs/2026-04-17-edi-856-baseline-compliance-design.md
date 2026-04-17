# EDI 856 Baseline Compliance Design (X12 4010)

## 1. Goal and Scope

### Goal
Verify and enforce **100% compliance** of this module against the **X12 4010 856 baseline**.

### In Scope
- 856 Ship Notice/Manifest baseline compliance only.
- 855 Purchase Order Acknowledgment support as an optional flow step.
- Deterministic compliance verification with rule-level failures.
- Compliance evidence suitable for release gating.

### Out of Scope
- Trading-partner-specific custom guides in this phase.
- Reworking ERPNext 850/810 behavior.

### Existing System Context
- ERPNext already covers 850 (Purchase Order) and 810 (Invoice).
- `asn_module` is responsible for ASN behavior and is the 856-focused surface.
- 855 must be supported, but bypass must remain possible when not required.

## 1.1 Flow Model with Optional 855

Supported sequences:
- `850 -> 855 -> 856 -> 810` when acknowledgment is required.
- `850 -> 856 -> 810` when acknowledgment is bypassed.

Default behavior:
- `requires_855_ack = false` (bypass by default).

Gating rule for 856:
- If `requires_855_ack = true`, block 856 until a valid 855 exists.
- If `requires_855_ack = false`, allow 856 without 855.

Trade-offs:
- Flag-based gating (recommended): explicit and operationally simple, but depends on correct partner configuration.
- Auto-detect gating: less manual setup, but higher complexity and higher false-positive/false-negative risk.

## 2. Terminology (Implementation Glossary)

- Segment-level constraints: Required/optional segment presence, repetition limits, and allowed placement.
- Element-level constraints: Required data elements, datatype/length/code validations inside each segment.
- Envelope validation: Structural integrity and control matching across ISA/IEA, GS/GE, ST/SE.
- HL hierarchy validation: Parent-child correctness and level semantics in shipment hierarchy.
- CTT consistency: Totals/count fields align with actual detail content per baseline rule.
- SE consistency: Segment count accuracy and ST02/SE02 control number match.

## 3. Approaches Considered

### Option 1: Compliance Matrix + Deterministic Validator (Recommended)
Build an explicit machine-readable 4010 856 baseline rule catalog and validate every payload against it.

Trade-offs:
- Pros: Highest auditability, repeatability, and testability for a 100% claim.
- Cons: Moderate upfront effort to codify rules cleanly.

### Option 2: Template-First Builder with Inline Guards
Embed compliance checks inside EDI generation templates.

Trade-offs:
- Pros: Faster initial implementation.
- Cons: Harder to prove complete coverage and harder to maintain as rules expand.

### Option 3: External EDI Validator Library + Adapter
Adopt a third-party validator and map module output to it.

Trade-offs:
- Pros: Less custom validation logic.
- Cons: Dependency/version risks, less control over diagnostics.

### Decision
Use **Option 1**.

## 4. Architecture (Approved)

### 4.1 Compliance Rule Model
- Add a versioned rule catalog for X12 4010 856 baseline.
- Every rule has a stable `rule_id` (examples):
  - `SEG-BSN-REQ-001`
  - `ELM-ST01-856-001`
  - `CNT-SE01-MATCH-001`

### 4.2 Validation Pipeline
1. Parse segments/elements from EDI payload.
2. Validate envelopes and control relationships.
3. Validate required segment presence and allowed ordering.
4. Validate HL hierarchy graph and parent linkage.
5. Validate element-level requirements and formats.
6. Validate cross-segment consistency (`CTT`, `SE`).
7. Apply optional 855 precondition for 856 release (`requires_855_ack` gate).
8. Return structured compliance result.

### 4.3 Compliance Result Contract
Return:
- `is_compliant: bool`
- `errors: list[ComplianceFinding]`
- `warnings: list[ComplianceFinding]`
- `computed_metrics` (segment counts, hierarchy stats, control references)

`ComplianceFinding` contains:
- `rule_id`
- `severity`
- `message`
- `segment_tag`
- `segment_index`
- `element_index` (optional)
- `fix_hint`

## 5. Component Boundaries

Create an isolated EDI compliance slice:

- `asn_module/edi_856/parser.py`
  - Tokenization + normalized segment model.
  - No business logic.

- `asn_module/edi_856/rules_4010.py`
  - Baseline 856 rule catalog.

- `asn_module/edi_856/validator.py`
  - Deterministic validation engine.

- `asn_module/edi_856/reporting.py`
  - Human-readable and JSON compliance reports.

- `asn_module/edi_856/tests/`
  - Positive and negative fixtures, plus regression tests.

Integration boundary:
- Existing ASN/856 export paths must pass this validator before output is accepted/emitted.

## 6. Error Handling Strategy

- Invalid EDI input should produce structured findings, not unhandled exceptions.
- Only true parser-internal faults should raise system errors.
- Messages must be actionable and mapped to stable `rule_id`s.

## 7. Verification Strategy (Proof for 100% Baseline Compliance)

### 7.1 Required Test Families
- Rule-family coverage tests (segment, element, structure, hierarchy, counts/controls).
- Golden valid fixtures: known-good baseline 856 payloads with zero errors.
- Mutation-style negative tests: one broken rule per fixture/assertion.
- Explicit `CTT` and `SE` mismatch tests.
- Parser robustness/property tests for malformed but parseable input patterns.

### 7.2 Coverage Standard
A 100% baseline claim requires:
1. All mandatory baseline rules are represented in the rule catalog.
2. Each mandatory rule family has positive and negative test coverage.
3. No uncovered mandatory rules in CI report.

## 8. Compliance Evidence and Release Gate

### 8.1 Evidence Artifacts
Generate and maintain:
- Baseline compliance matrix (rule -> test mapping).
- CI summary by rule family.
- Uncovered-rule report (must be zero for release).

### 8.2 Release Gate
Compliant release allowed only when:
1. Compliance suite passes.
2. Mandatory uncovered rules = 0.
3. No open high-severity parser/validator defects.

Trade-off:
- Strict gates reduce regression risk and strengthen compliance claims, but increase development friction when changing EDI behavior.

## 9. Explicit Definition of “100% Compliant” (This Scope)

For this project phase, “100% compliant” means:
- The module passes all codified **X12 4010 856 baseline** mandatory rules,
- With no structural violations,
- With no control/count inconsistencies,
- And with CI evidence proving full mandatory-rule coverage.

## 10. Deferred Next Phase

After baseline completion:
- Add partner-specific override layers on top of baseline rules.
- Keep baseline validator immutable and apply partner profiles as additive constraints.
