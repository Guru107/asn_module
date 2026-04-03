# Native Scan Integration Design

## Summary

Align ASN Module scanning with Frappe and ERPNext native patterns wherever those patterns fit, while keeping the existing QR action engine for workflow dispatch. The target architecture is hybrid: native ERPNext scan UX for form-level operator interaction, custom ASN backend logic for token decoding, action routing, permission checks, scan logging, and post-scan document navigation.

This avoids rebuilding framework-native item barcode behavior, and it also avoids forcing ASN workflow tokens into ERPNext's item/barcode lookup model where they do not fit.

## Problem

ASN Module currently has custom scan entry points:
- a dedicated Desk page: `scan-station`
- a global scan dialog opened by keyboard shortcut

Those entry points are custom even though ERPNext already ships native barcode scanning patterns, including:
- `erpnext.utils.BarcodeScanner`
- `scan_barcode` fields on stock transactions such as `Purchase Receipt`
- stock-form scanning flows that are familiar to ERPNext users

The module should be as close to framework-native behavior as possible, but the business workflow is not plain item barcode scanning. ASN Module uses tokenized QR dispatch for actions such as:
- create Purchase Receipt from ASN
- create Purchase Invoice from Purchase Receipt
- confirm putaway
- later workflow-specific handlers

ERPNext native barcode scanning does not natively provide receipt-level workflow dispatch, action registry lookup, or scan audit logging for these actions.

## Goals

- Reuse ERPNext-native scanning UX and APIs wherever they are a good fit
- Preserve the current QR action engine as the single workflow-dispatch backend
- Reduce custom frontend scanning code where framework-native patterns already exist
- Keep generated QR assets and token contracts valid
- Keep operator UX familiar to ERPNext users

## Non-Goals

- Replace the QR token engine with ERPNext item barcode lookup
- Redesign workflow handlers around item barcode semantics
- Change token format, dispatch endpoint contract, or scan log model
- Remove all custom scan UI immediately regardless of workflow needs

## Current State

### Native framework capabilities available

ERPNext already provides:
- `erpnext.utils.BarcodeScanner` in `erpnext/public/js/utils/barcode_scanner.js`
- `scan_barcode` fields in stock transaction doctypes including `Purchase Receipt`
- native item, batch, serial, and warehouse scan processing via `erpnext.stock.utils.scan_barcode`

These capabilities are optimized for item-level and warehouse-level scanning inside document forms.

### ASN Module custom capabilities already implemented

ASN Module currently provides:
- token generation and verification
- `asn_module.qr_engine.dispatch.dispatch` for workflow routing
- scan logging in `Scan Log`
- a dedicated `Scan Station` page
- a global scan dialog opened via shortcut
- domain-specific workflow handlers that create or open documents

These capabilities are optimized for workflow-token scanning rather than item barcode lookup.

## Design Decision

Use a hybrid model:
- use native ERPNext scanning UX patterns where scanning happens inside stock forms
- keep ASN Module custom backend dispatch for workflow-token interpretation and routing
- keep a thin custom adapter layer only where native ERPNext does not provide workflow-token handling

This is the best fit because it maximizes framework reuse without misusing the native barcode model.

## Architecture

### 1. Backend stays custom and centralized

The backend authority for workflow scans remains:
- `asn_module.qr_engine.dispatch.dispatch`

Responsibilities that remain custom:
- token extraction and verification
- action registry lookup
- role and permission checks
- workflow handler invocation
- scan logging
- response contract for frontend navigation

Reason:
ERPNext native barcode scanning resolves item/barcode data. ASN Module needs workflow routing based on signed tokens and domain-specific actions.

### 2. Native scanner UX becomes the preferred frontend pattern

Where a user is already working inside ERPNext stock forms, scanning should follow framework-native patterns:
- use `scan_barcode` style fields where appropriate
- use `erpnext.utils.BarcodeScanner` behavior as the baseline interaction model
- keep scanner ergonomics aligned with ERPNext forms and keyboard flow

Reason:
This reduces custom UX debt and matches user expectations inside ERPNext.

### 3. Custom scan UI remains only where native ERPNext has no equivalent

Custom UI remains valid for:
- workflow-token scanning from anywhere in Desk
- scan history review tied to `Scan Log`
- a dedicated operations fallback screen
- direct navigation to created or opened documents after workflow dispatch

Reason:
ERPNext does not provide a native receipt-level workflow dispatch console.

## Component Boundaries

### Native components

Use native ERPNext capabilities for:
- scanner input capture behavior
- scan-field conventions on forms
- barcode-scanner event flow inside stock transactions
- item, serial, batch, and warehouse barcode resolution where applicable

### ASN Module components

Keep ASN Module responsible for:
- QR token generation
- QR token verification
- dispatch endpoint behavior
- workflow action handlers
- scan logging
- post-scan route resolution
- workflow-specific user messages

### Thin adapter layer

A small custom adapter is still required between native-feeling scan input and the ASN dispatch backend.

Its job is limited to:
- accepting scanner input
- extracting `token` from a full scanned URL when needed
- calling `asn_module.qr_engine.dispatch.dispatch`
- handling success and failure UI
- navigating to the returned route

It should not reimplement item barcode logic that ERPNext already owns.

## UI Strategy

### Primary UX

Primary scanning UX should shift toward native ERPNext form contexts wherever that fits the operator workflow.

Examples:
- `Purchase Receipt` form scanning should prefer the native `scan_barcode` pattern for item-level receipt operations
- future stock workflows should prefer the same native pattern if the business action is item-oriented

### Fallback UX

`Scan Station` remains, but as a fallback operational screen rather than the primary scanning model.

Recommended role of `Scan Station`:
- operational console for shared scanning stations
- scan history view for recent workflow actions
- fallback input surface for scanners that are not used inside a form context

### Global shortcut

The global shortcut remains acceptable, but it should be treated as a convenience layer rather than the core scan architecture.

It should evolve toward a thin adapter that feels consistent with framework-native input handling rather than a fully custom scanning workflow.

## Practical Migration Strategy

### Phase 1: Keep backend stable

No backend contract changes:
- keep token format unchanged
- keep dispatch endpoint unchanged
- keep handler contracts unchanged
- keep `Scan Log` unchanged
- keep generated QR assets unchanged

This minimizes risk and preserves already-issued QR codes.

### Phase 2: Reduce custom frontend behavior

Review the current custom scan entry points:
- `asn_module/asn_module/page/scan_station/scan_station.js`
- `asn_module/public/js/scan_dialog.js`

Refactor them toward a thin adapter model:
- less custom buffering logic where native patterns suffice
- more consistent scanner-field behavior
- shared token extraction and dispatch wiring

### Phase 3: Prefer native form integration

Where workflow execution naturally starts from a stock form, attach scanning closer to the document rather than through a separate standalone screen.

This does not mean replacing workflow-token scanning with item-barcode scanning. It means using ERPNext-native interaction patterns where scanning happens.

## Trade-Offs

### Recommended hybrid model

Pros:
- closest practical fit to Frappe and ERPNext conventions
- preserves the QR workflow architecture already implemented
- reduces custom UX maintenance
- keeps user interaction familiar inside ERPNext forms

Cons:
- not a fully native solution end-to-end
- still requires a small custom adapter layer
- `Scan Station` and shortcut UX remain partially custom because ERPNext has no true equivalent for workflow-token dispatch

### Fully custom approach

Pros:
- complete control over behavior
- minimal redesign from current implementation

Cons:
- duplicates framework scanning concepts
- higher long-term maintenance
- less aligned with ERPNext user expectations

### Full native redesign

Pros:
- maximum theoretical framework alignment

Cons:
- poor fit for workflow-token dispatch
- would distort business logic into the wrong abstraction
- high churn for limited benefit

## Error Handling

The adapter layer should keep current behavior:
- invalid token or dispatch failure returns a clear error
- errors remain logged in `Scan Log`
- frontend shows concise failure feedback
- successful dispatch continues to navigate to the returned document route

No additional scanning error framework is needed beyond existing dispatch and log behavior.

## Testing Strategy

### Keep backend tests centered on custom dispatch behavior

Continue to prioritize tests for:
- token verification
- dispatch routing
- handler behavior
- scan logging

### Add targeted adapter tests only

If scan UI is refactored toward native patterns, test only the adapter behavior:
- extraction of token from scanned URL
- direct token pass-through when only the token is scanned
- dispatch API call wiring
- success-route navigation
- failure feedback behavior

### Avoid rebuilding ERPNext scanner tests

Do not duplicate tests for native ERPNext item barcode handling. That behavior belongs to ERPNext.

## Risks

- Over-rotating toward “native” could push workflow-token logic into ERPNext barcode abstractions that were not designed for it
- Leaving too much custom JS in place defeats the goal of framework alignment
- Form-level integration may improve operator flow but can introduce UI churn if rolled out without clear scope boundaries

## Recommendation

Adopt the hybrid architecture immediately:
- keep the ASN QR action engine and dispatch backend unchanged
- reduce custom frontend scanning logic where ERPNext-native patterns already solve the interaction problem
- treat `Scan Station` as a fallback operations screen, not the primary architectural center
- prefer native-form scanning patterns for future scan integrations on stock doctypes

## Success Criteria

This design is successful if:
- workflow-token scans still go through a single ASN dispatch backend
- existing QR tokens and generated files remain valid
- scanning UX on stock forms becomes more ERPNext-native
- custom scan JS shrinks to a thin adapter instead of owning the full interaction model
- `Scan Station` remains available as a fallback and history console, not a required custom workflow hub
