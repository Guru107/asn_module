# ASN Module - Design Specification

## Overview

A QR-driven stock entry and material movement automation module for ERPNext (Frappe v16). Streamlines the entire inward supply chain - from supplier shipping notification through quality inspection to final invoicing - using scannable QR codes at every handoff point.

## Architecture: QR Action Engine + Domain Doctypes

Two layers:

1. **QR Action Engine** - generic framework that encodes/decodes QR URLs, routes scan events to registered action handlers, and logs every scan
2. **Domain Doctypes & Handlers** - ASN and supporting logic. Each workflow registers its QR actions with the engine.

---

## Section 1: QR Action Engine (Core Framework)

### QR URL Format

```
https://{site}/api/method/asn_module.qr_engine.dispatch?token={encrypted_token}
```

The token is an encrypted payload containing:

```json
{
  "action": "create_purchase_receipt",
  "source_doctype": "ASN",
  "source_name": "ASN-00001",
  "created_at": "2026-03-31T10:00:00",
  "created_by": "supplier@example.com"
}
```

Encryption prevents tampering - users cannot modify the QR to change quantities or target documents.

### Doctypes

**QR Action Registry** (Single doctype with child table rows)

Registers available actions:

| Field | Type | Description |
|---|---|---|
| action_key | Data | Unique key, e.g., `create_purchase_receipt` |
| handler_method | Data | Python dotted path, e.g., `asn_module.handlers.purchase_receipt.create_from_asn` |
| allowed_roles | Table (QR Action Role) | Roles permitted to execute this action |
| source_doctype | Link (DocType) | Which doctype this action operates on |

**Scan Log**

| Field | Type | Description |
|---|---|---|
| scan_timestamp | Datetime | Auto-set |
| user | Link (User) | Who scanned |
| action | Data | Action key executed |
| source_doctype | Link (DocType) | |
| source_name | Dynamic Link | |
| result | Select | Success / Failure |
| result_doctype | Link (DocType) | Created document type |
| result_name | Dynamic Link | Created document name |
| error_message | Text | If failure |
| device_info | Data | Desktop / Mobile |

### Dispatch Flow

1. User scans QR -> hits `/dispatch` API
2. Engine decrypts token, validates action exists in registry
3. Checks user has permitted role for that action
4. Calls the registered handler method
5. Handler creates the document, returns `{doctype, name, url}`
6. Engine logs the scan in Scan Log
7. Response: desktop browser redirects to the document; mobile app opens the form

### QR Generation Utility

- Method: `generate_qr(action, source_doctype, source_name)`
- Returns both QR image (PNG) and the raw URL
- QR images stored as File attachments on the source document
- Barcode (Code 128) also generated alongside QR for handheld scanner compatibility

---

## Section 2: ASN (Advanced Shipping Notice) Doctype

### Fields

| Field | Type | Description |
|---|---|---|
| supplier | Link (Supplier) | Auto-set from logged-in supplier |
| items | Table (ASN Item) | Child - line items being shipped |
| vehicle_number | Data | Transport vehicle |
| transporter_name | Data | Transporter/driver |
| driver_contact | Data | Driver phone number |
| supplier_invoice_no | Data | Supplier's sales invoice reference |
| supplier_invoice_date | Date | |
| supplier_invoice_amount | Currency | |
| expected_delivery_date | Date | |
| remarks | Text | |
| qr_code | Attach Image | Generated QR for receipt creation |
| barcode | Attach Image | Code 128 barcode equivalent |
| status | Select | Draft / Submitted / Partially Received / Received / Closed |
| asn_date | Date | Auto-set on submission |

### ASN Item (Child Table)

| Field | Type | Description |
|---|---|---|
| purchase_order | Link (Purchase Order) | Which PO this line belongs to |
| purchase_order_item | Data | PO item reference for precise tracking |
| item_code | Link (Item) | Pulled from PO |
| item_name | Data | |
| qty | Float | Quantity being shipped (can be less than PO qty) |
| uom | Link (UOM) | |
| rate | Currency | From PO |
| batch_no | Data | Optional - only if item has batch tracking |
| serial_nos | Small Text | Optional - only if item has serial tracking |
| received_qty | Float | Read-only, updated on PR submission |
| discrepancy_qty | Float | Read-only, qty - received_qty |

### Supplier Portal Workflow

1. Supplier logs into portal, creates new ASN
2. Selects one or more open Purchase Orders - items populate automatically
3. Supplier adjusts quantities for partial shipments, adds batch/lot where applicable
4. Enters vehicle, transporter, invoice details
5. Submits ASN
6. System generates Purchase Receipt QR (action: `create_purchase_receipt`, source: this ASN)
7. Supplier prints QR code on their sales invoice / delivery challan

### Validation Rules

1. Shipped qty per item cannot exceed remaining unshipped PO qty (accounting for all previous ASNs and receipts)
2. At least one item required
3. Supplier can only select their own POs with status "To Receive and Bill" or "To Receive"
4. Unique constraint on `supplier` + `supplier_invoice_no` - hard block, prevents double-booking the same supplier invoice/challan

### Discrepancy Tracking

When a Purchase Receipt is created from ASN and quantities are edited before submission:

- ASN Item's `received_qty` and `discrepancy_qty` update when the linked Purchase Receipt is submitted
- ASN status moves to "Partially Received" if not all items/quantities are received
- ASN status moves to "Received" when all items are fully received

---

## Section 3: Gate Entry

**Deferred.** An existing Gate Entry doctype is in use. Integration with the ASN module will be taken up as a separate effort later.

---

## Section 4: Purchase Receipt from ASN Scan

Uses ERPNext's native **Purchase Receipt** doctype. No new doctype needed.

### Handler: `create_purchase_receipt`

When store user scans ASN's Purchase Receipt QR:

1. Validates ASN status is "Submitted" or "Partially Received"
2. Duplicate scan guard: if a draft Purchase Receipt already exists for this ASN, opens the existing draft instead of creating a new one
3. Creates Purchase Receipt in **draft** mode with:
   - `supplier` from ASN
   - Line items from ASN Items: `item_code`, `qty`, `uom`, `rate`, `batch_no`, `serial_nos`
   - Each item linked back to its `purchase_order` and `purchase_order_item`
   - Custom field `asn` on Purchase Receipt linking back to the ASN
   - `set_warehouse` based on item's "Inspection Required before Purchase" flag:
     - If inspection required -> Quality Inspection warehouse
     - If not required -> default accepted warehouse
4. Returns the draft Purchase Receipt URL

### Custom Fields on Purchase Receipt

| Field | Type | Description |
|---|---|---|
| asn | Link (ASN) | Source ASN reference |
| asn_items | Hidden/JSON | Mapping of PR items to ASN items for discrepancy tracking |

### Verification & Submission Flow

1. Store user reviews the draft - verifies physical quantities against PR line items
2. Adjusts quantities if there's a discrepancy (received less/more than ASN stated)
3. Submits the Purchase Receipt
4. On submit hook:
   - Updates ASN Item's `received_qty` and `discrepancy_qty`
   - Updates ASN status: "Received" if all items fully received, "Partially Received" otherwise
   - For items with inspection required: triggers the QC flow (Section 5)
   - For items without inspection: generates Putaway QR (action: `confirm_putaway`, source: this PR, filtered to non-QC items)

### Validation

- Cannot create PR from an ASN that is already "Received" or "Closed"

---

## Section 5: Quality Inspection & Stock Transfer Flow

Uses ERPNext's native **Quality Inspection** and **Stock Entry** doctypes.

### QC Flow

1. Purchase Receipt submitted with QC items -> items sit in Quality Inspection warehouse
2. Quality team creates Quality Inspection against the Purchase Receipt (standard ERPNext flow)
3. On Quality Inspection submit hook, the ASN module:
   - Reads inspection result (Accepted / Rejected / Partial)
   - For **accepted items**: generates Stock Transfer QR (action: `create_stock_transfer`, source: Quality Inspection, with accepted qty and destination warehouse)
   - For **rejected items**: generates Purchase Return QR (action: `create_purchase_return`, source: Quality Inspection, with rejected qty)
   - Both QR codes attached to the Quality Inspection document

### Handler: `create_stock_transfer`

When store user scans the Stock Transfer QR:

1. Creates a **Stock Entry** (type: Material Transfer) in draft mode
2. Pre-filled with:
   - Source warehouse: Quality Inspection warehouse
   - Destination warehouse: item's default warehouse or main store
   - Items with accepted quantities from Quality Inspection
   - Reference back to Purchase Receipt and Quality Inspection
3. Store user reviews and submits
4. On submit: updates ASN status if all items now fully processed

### Handler: `create_purchase_return`

When store user scans the Purchase Return QR:

1. Creates a **Purchase Receipt** (is_return = 1) in draft mode
2. Pre-filled with:
   - Rejected items and quantities from Quality Inspection
   - Source warehouse: Quality Inspection warehouse
   - Linked to original Purchase Receipt
3. Store user reviews and submits
4. On submit: updates ASN discrepancy tracking with rejection details

### Items Without QC

Items that don't require inspection go directly to the accepted warehouse via the Purchase Receipt. The Putaway QR from Section 4 handles bin-level placement for these items.

---

## Section 6: Purchase Invoice from Scan

Uses ERPNext's native **Purchase Invoice** doctype.

### QR Generation

When a Purchase Receipt is submitted, the ASN module generates a Purchase Invoice QR (action: `create_purchase_invoice`, source: Purchase Receipt) attached to the Purchase Receipt.

### Handler: `create_purchase_invoice`

When accounts team scans the Purchase Invoice QR:

1. Validates Purchase Receipt is submitted and not already fully billed
2. Duplicate guard: if a draft Purchase Invoice already exists for this Purchase Receipt, opens the existing draft instead of creating a new one
3. Creates **Purchase Invoice** in draft mode with:
   - `supplier` from Purchase Receipt
   - Line items from Purchase Receipt with received quantities and rates
   - `bill_no` populated from ASN's `supplier_invoice_no`
   - `bill_date` populated from ASN's `supplier_invoice_date`
   - Custom field `asn` linking back to the ASN
   - Standard ERPNext link to Purchase Receipt on each item row
4. Returns draft Purchase Invoice URL

### Custom Fields on Purchase Invoice

| Field | Type | Description |
|---|---|---|
| asn | Link (ASN) | Source ASN reference |

### Validation

- Purchase Receipt must be in submitted state
- Only users with "Accounts User" or "Accounts Manager" role can execute this action

---

## Section 7: Putaway (Bin Location) Confirmation

### QR Generation

When a stock transfer (from QC) or Purchase Receipt (non-QC items) is submitted, the system generates a **Putaway QR** per item line encoding:

- Item code
- Quantity
- Suggested bin/shelf location (from Item's default warehouse or Putaway Rule if configured)

### Handler: `confirm_putaway`

When store user scans the Putaway QR at the shelf location:

1. Creates a **Scan Log** entry confirming the item was placed at the correct location
2. No new stock movement - stock is already in the correct warehouse from the previous step
3. This is a confirmation/audit step, not a transfer

### Why Not a Stock Entry?

ERPNext's Putaway Rule already handles warehouse-level placement during Purchase Receipt. This QR step adds bin-level confirmation - verifying that the physical placement matches the system's expectation.

### Mismatch Handling

If the user scans at a different bin than suggested, the system logs the actual location and can update the item's bin reference for future picks.

---

## Section 8: Subcontracting Flows

### 8a: Raw Material Dispatch to Job Worker

**QR Generation**: When a Subcontracting Order is submitted, the ASN module generates a Material Dispatch QR (action: `create_subcontracting_dispatch`, source: Subcontracting Order) attached to the order.

**Handler: `create_subcontracting_dispatch`**

When store user scans the QR:

1. Creates a **Stock Entry** (type: Send to Subcontractor) in draft mode
2. Pre-filled with:
   - Source warehouse: main store / raw material warehouse
   - Destination warehouse: job worker's warehouse (supplier warehouse on Subcontracting Order)
   - Items: raw materials and quantities as per the Subcontracting Order's service items BOM
3. Store user reviews, adjusts if partial dispatch, submits
4. On submit: generates a printable QR on the Stock Entry for the job worker to use when sending finished goods back (action: `create_subcontracting_receipt`, source: Subcontracting Order)

### Validation

- Cannot dispatch more raw materials than Subcontracting Order requires (accounting for previous dispatches)

### 8b: Finished Goods Receipt from Job Worker

**QR Generation**: The Stock Entry from 8a carries a QR (action: `create_subcontracting_receipt`, source: Subcontracting Order) that goes with the dispatched materials to the job worker.

**Handler: `create_subcontracting_receipt`**

When job worker delivers finished goods and store user scans the QR:

1. Creates a **Subcontracting Receipt** in draft mode
2. Pre-filled with:
   - Finished goods items and expected quantities from Subcontracting Order
   - Supplier (job worker) details
   - Link back to Subcontracting Order and dispatch Stock Entry
   - Warehouse: if finished goods item has inspection required -> QC warehouse, otherwise -> main store
3. Store user verifies received quantities, submits
4. On submit: follows the same QC/non-QC split as Purchase Receipts (Section 5 logic reused)

### Validation

- Cannot receive more finished goods than ordered quantity

---

## Section 9: Scan Station & Mobile Scanning Interface

### Desktop: Scan Station Page

A dedicated page at `/app/scan-station`:

- Large input field that auto-focuses on page load - receives input from handheld USB/Bluetooth QR scanners
- Scanner input triggers the QR dispatch automatically (no button click needed)
- On successful document creation: redirects to the new document
- On error: displays the error message inline with option to retry
- Recent scan history shown below the input (last 20 scans from Scan Log)
- Role-based: shows only actions the current user is permitted to perform

### Desktop: Global Scan Shortcut

- Keyboard shortcut (e.g., `Ctrl+Shift+S`) opens a scan dialog from anywhere in ERPNext
- Same input field behavior as Scan Station
- On successful scan: navigates to the created/opened document
- Lightweight alternative for occasional scanning (accounts team)

### Mobile: ERPNext Mobile App

- Add a "Scan" button to the mobile app's bottom navigation or home screen
- Opens the device camera for QR scanning
- On successful scan: opens the created document in the mobile app
- Same dispatch API as desktop - no separate mobile logic

### Dispatch API Response

```json
{
  "success": true,
  "action": "create_purchase_receipt",
  "doctype": "Purchase Receipt",
  "name": "MAT-PRE-2026-00001",
  "url": "/app/purchase-receipt/MAT-PRE-2026-00001",
  "message": "Purchase Receipt created from ASN-00001"
}
```

Both desktop and mobile clients use this response to navigate the user to the document.

---

## Section 10: Notifications & Permissions

### Notifications

| Event | Recipient | Channel |
|---|---|---|
| ASN submitted by supplier | Store Manager | Email + System Notification |
| Purchase Receipt created from scan | Store User (creator) + Store Manager | System Notification |
| QC items awaiting inspection | Quality Inspector role | System Notification |
| Quality Inspection submitted | Store User (for stock transfer) | System Notification |
| Purchase Receipt ready for billing | Accounts User | System Notification |
| Discrepancy detected (ASN vs PR) | Store Manager + Purchase Manager | Email + System Notification |
| Purchase Return created (QC rejection) | Supplier + Purchase Manager | Email + System Notification |
| Subcontracting materials dispatched | Job Worker (supplier) | Email |
| Subcontracting receipt created | Store Manager | System Notification |

### Role-Action Matrix

| Action | Allowed Roles |
|---|---|
| Create ASN (portal) | Supplier |
| create_purchase_receipt | Stock User, Store Manager |
| create_stock_transfer | Stock User, Store Manager |
| create_purchase_return | Stock User, Store Manager |
| confirm_putaway | Stock User, Store Manager |
| create_purchase_invoice | Accounts User, Accounts Manager |
| create_subcontracting_dispatch | Stock User, Store Manager |
| create_subcontracting_receipt | Stock User, Store Manager |

### Permission Model

- **ASN doctype**: Suppliers see only their own ASNs via portal. Internal users with Stock User / Stock Manager role have full access.
- **QR Action Registry**: only System Manager can configure actions
- **Scan Log**: read-only for all roles, write via system only (no manual creation)

---

## New Doctypes Summary

| Doctype | Type | Description |
|---|---|---|
| ASN | Document | Advanced Shipping Notice |
| ASN Item | Child Table | Line items in an ASN |
| QR Action Registry | Single | Registers available QR-triggered actions |
| QR Action Role | Child Table | Allowed roles per action in registry |
| Scan Log | Document | Audit log of every QR scan |

## Custom Fields on Existing Doctypes

| Doctype | Field | Type | Description |
|---|---|---|---|
| Purchase Receipt | asn | Link (ASN) | Source ASN reference |
| Purchase Receipt | asn_items | Hidden/JSON | ASN item mapping for discrepancy tracking |
| Purchase Invoice | asn | Link (ASN) | Source ASN reference |

## Native Doctypes Used As-Is

Purchase Receipt, Purchase Invoice, Quality Inspection, Stock Entry, Subcontracting Order, Subcontracting Receipt
