# Sales Invoice 1D Barcode (16-Char Mapped Code) Design

## Goal
Support supplier invoice scanning using **1D barcode only** (Code128), without adding any QR code to Sales Invoice. Ensure scan reliability and easy supplier adoption while preserving existing ASN -> Purchase Receipt dispatch behavior.

## Confirmed Constraints
- Do not add QR on Sales Invoice (India e-invoice IRN QR already exists).
- Prefer barcode approach with broad supplier ecosystem support (small and large suppliers).
- Do not depend on supplier ERP integration/API capability.
- Supplier workflow must be simple: copy-paste value into ASN field on their invoice system.

## Final Workflow
1. ASN is created in our system.
2. System generates a **16-character mapped scan code** for that ASN/action.
3. Supplier copies this 16-char code from ASN portal/details and pastes it into their invoice ASN field.
4. Supplier invoice prints a **Code128** barcode from that field.
5. On receiving goods, our scanner reads barcode and dispatch flow creates Purchase Receipt.

## Barcode Strategy
- Symbology: `Code128` (existing path retained).
- Encoded value: raw 16-char mapped code from Scan Code registry.
- Human-readable display label: grouped format `XXXX-XXXX-XXXX-XXXX`.
- Barcode still encodes raw value (no dashes).

## Data Model and Mapping
- Continue using `Scan Code` doctype as source of truth.
- Update new-code generation length constant from `12` to `16`.
- Keep existing alphabet (uppercase, unambiguous characters).
- Keep action/source mapping server-side.
- Barcode payload remains opaque key only; business context resolved on backend.

## Cutover and Backward Compatibility
- **Do not invalidate existing 12-char codes.**
- Existing active 12-char scan codes must remain scannable through current lifecycle rules until they are naturally consumed/revoked/expired.
- Only **newly generated** codes use 16-char format.
- Dispatch and lookup logic must accept both lengths during transition.
- Generation logic must never create new 12-char codes after rollout.

Rationale:
- Prevent breaking in-flight supplier invoices already printed with 12-char codes.
- Allow zero-downtime migration with no supplier-side coordination window.

## Supplier Compatibility Model
No supplier-system integration required.
- Supplier only receives a printable/copiable 16-char code.
- Supplier ERP only needs ability to print Code128 from text field.

## Dispatch and Validation
- Scanner input -> normalize code -> lookup `Scan Code` registry.
- Validate lifecycle/state/action/source via existing dispatch logic.
- On success: execute `create_purchase_receipt` action path.
- Keep existing failure handling for missing/invalid/revoked/used code.

Normalization rules:
- Trim surrounding whitespace.
- Strip internal spaces and `-`.
- Uppercase before lookup.
- Accept both 12-char (legacy) and 16-char (new) canonical forms.

## Printability and Scan Reliability Guardrails
- Preserve existing Code128 render path and tune only if needed after test evidence.
- Keep barcode label readable beneath image.
- Avoid over-encoding payload; 16-char opaque code keeps barcode width manageable for invoice templates.

## Security
- Opaque mapped code only (no sensitive context printed in barcode).
- Server-side authorization and state checks remain the enforcement layer.

## Trade-offs
### Chosen: 1D Code128 + 16-char mapped code
- Pros:
  - Works with widely deployed 1D scanners.
  - No new scanner/app rollout required.
  - Supplier workflow stays simple (copy/paste field value).
- Cons:
  - Less data density than 2D symbols.
  - Requires backend lookup for full context.

### Explicitly not chosen
- DataMatrix/2D payload on invoice:
  - Better density but lower ecosystem fit for current supplier operations and scanner assumptions.
- Full offline payload barcode:
  - Higher complexity, larger symbol footprint, greater print/layout risk.

## Testing Strategy
### Unit
- Scan code generation length/charset assertions updated for 16 chars (new generation path).
- Legacy 12-char codes remain accepted by normalization/lookup path.
- Barcode generation contract remains valid for 16-char value.
- Dispatch accepts both 12-char and 16-char code shapes.

### Integration
- End-to-end ASN -> scan barcode -> Purchase Receipt creation using generated mapped code.
- Negative paths: invalid/missing/revoked/used codes.

### E2E
- Supplier-like flow in portal context:
  - obtain mapped code from ASN
  - scan/dispatch using that code
  - verify PR creation and state updates

## Acceptance Criteria
- New ASN-generated mapped code length is 16.
- Existing 12-char active codes remain scannable during migration.
- Supplier can copy 16-char code into invoice field and print Code128.
- Our scanner successfully reads and dispatches to PR creation.
- No QR dependency added to Sales Invoice flow.
- Existing IRN QR on invoice remains unaffected.
- Print/scan reliability check passes with at least 95% successful scans on test sample prints at agreed invoice print settings.
