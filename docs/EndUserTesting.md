# ASN Module: End User Test Script

A step-by-step script to test the whole ASN Module the way end users use it: suppliers on the portal, gate and stores staff at the desk, and accounts. Work through the sections in order. Later sections reuse documents created earlier.

Terms follow `CONTEXT.md` (ASN, Material ASN, Job ASN, Gate Pass Mode, Scan Code, Shipped Qty, Remaining Qty, Stock Cap, and so on).

## How to record results

- Mark each test **Pass**, **Fail** or **Blocked** in the Result column.
- On a Fail, note the document name, the exact error text, and a screenshot. Then go on to the next test unless the section says to stop.
- "Desk" means `/app`. "Portal" means the supplier website at `/asn`.
- Use a private or second browser for the supplier user, so you can stay logged in as a desk user at the same time.

| Tester | Site | Frappe / ERPNext version | Date |
|--------|------|--------------------------|------|
|        |      |                          |      |

---

## 1. Setup (do once)

### 1.1 Site checks

| # | Check | Expected | Result |
|---|-------|----------|--------|
| S-1 | `asn_module` is installed and `bench --site <site> migrate` ran without errors | Migrate finishes clean | |
| S-2 | Site config has `host_name` set to the site's public URL | Needed so printed QR codes point at the right domain | |
| S-3 | The **Gate Pass** DocType exists on the site (needed only for section 7 and 8.3) | Gate Pass list opens. The form has an **ASN** link field (after Supplier, unless the site already had its own `asn` field) and a read-only **Scan Code** field. Each item row has a read-only **ASN Item** field: open the row to see it, it is not a grid column | |
| S-4 | Desk > Notification list has **ASN Submitted** and **Purchase Receipt Ready for Billing**, both enabled | Both present. ASN Submitted: email plus system notification to Stock Manager. Ready for Billing: system notification only, to Accounts User | |
| S-5 | Outgoing email is set up (or you can read Email Queue) | Emails from section 3.5 and 4.3 can be checked | |

### 1.2 Users

Create these users. Give each one only the roles listed.

| User | Type | Roles | Used for |
|------|------|-------|----------|
| `supplier.a@test` | Website User | Supplier (contact linked to **Supplier A**) | Portal |
| `supplier.b@test` | Website User | Supplier (contact linked to **Supplier B**) | Portal permission checks |
| `stores.user@test` | System User | Stock User | Scanning, receipts, Gate Pass |
| `stores.mgr@test` | System User | Stock User + Stock Manager | ASN submit/cancel, Stock Cap setup. Stock Manager alone has no read on Purchase Order or Subcontracting Order in stock ERPNext, so the PO picker and scans would fail without Stock User |
| `accounts.user@test` | System User | Accounts User | Purchase Invoice, reports |
| Administrator / System Manager | System User | System Manager | ASN Settings |

To link a portal user to a supplier: open the Supplier, go to the **Portal Users** tab, add the user in **Supplier Portal Users**, and save. ERPNext adds the **Supplier** role on save. A Contact link alone is not enough: the app finds the supplier only from this table.

Portal drafts hold back Remaining Qty on their PO lines, and a supplier cannot delete a draft from the portal. Where a step says "no items", save the header only, or later quantities will not match.

Bulk upload runs on the `long` queue, so a worker must be running for section 3.5.

If the Gate Pass DocType has its own permissions on your site, give `stores.user@test` the roles it needs to create and submit a Gate Pass.

### 1.3 Master data

| Record | Values |
|--------|--------|
| Suppliers | **Supplier A**, **Supplier B** |
| Items (stock items, UOM Nos) | **ITEM-A**, **ITEM-B**, **ITEM-C** (used for Stock Cap) |
| Subcontracting items | **SVC-JOB** (service item, Maintain Stock off) for the subcontracting PO line. **FG-JOB** (stock item, Is Sub Contracted Item) with a default BOM that consumes **RM-JOB**. **RM-JOB** (stock item) with stock in Stores - N |
| Warehouses | **Stores - N**, **Stores - S** (leaf), and a leaf supplier warehouse **Job Work - A**. A warehouse has no Branch field: 9-1 ties Stores - N to Branch North through ASN Stock Cap Settings |
| Branches | **Branch North**, **Branch South** |
| Stock Settings | Over Delivery/Receipt Allowance = **0%** (section 6.1 changes it) |

### 1.4 Orders

Create and submit these. Write down their names.

| Ref | Document | Supplier | Lines | Warehouse |
|-----|----------|----------|-------|-----------|
| **PO-1** | Purchase Order | Supplier A | ITEM-A 100 Nos, ITEM-B 50 Nos | Stores - N |
| **PO-2** | Purchase Order | Supplier A | ITEM-A 40 Nos | Stores - N |
| **PO-3** | Purchase Order | Supplier A | ITEM-A 30 Nos | Stores - N |
| **PO-B** | Purchase Order | Supplier B | ITEM-B 20 Nos | Stores - N |
| **PO-CAP** | Purchase Order | Supplier A | ITEM-C 200 Nos | Stores - N |
| **SCO-1** | Subcontracting Order, made from a subcontracting PO (Is Subcontracted ticked; line SVC-JOB, FG Item FG-JOB, FG Item Qty 10; Supplier Warehouse Job Work - A) | Supplier A | FG-JOB 10 Nos; raw-material reserve warehouse Stores - N | Stores - N |
| **SCO-2** | Same as SCO-1 (used in 8.3) | Supplier A | FG-JOB 10 Nos | Stores - N |
| **PO-4** to **PO-8** | Purchase Order, one each for section 7 | Supplier A | ITEM-A 20 Nos, ITEM-B 10 Nos | Stores - N |
| **PO-9** | Purchase Order (7-15) | Supplier A | ITEM-A 100 Nos | Stores - N |
| **PO-ALW** | Purchase Order (section 6.1) | Supplier A | ITEM-A 100 Nos | Stores - N |

---

## 2. Settings

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 2-1 | As System Manager, open **ASN Settings** | One checkbox, **Gate Pass Mode**, unticked by default | |
| 2-2 | As `stores.mgr@test`, try to open ASN Settings | Not permitted | |
| 2-3 | Leave Gate Pass Mode **off** for now | Saved | |

Stock Cap setup is tested in section 9.

---

## 3. Supplier portal

Log in as `supplier.a@test`.

### 3.1 List and access

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-1 | Open `/asn` | "Advanced Shipping Notices" list. Only Supplier A's ASNs show (or "No ASNs found.") | |
| 3-2 | Open `/asn_new` | Page heading **Create ASN** with tabs **Single ASN** and **Bulk ASN Upload**. The single form is titled **New ASN** / **Not Saved** and has a **Save** button | |
| 3-3 | Log out. Log in as a desk user who is not in any Supplier's Portal Users table (Administrator works) and open `/asn_new` | **Not Permitted** page: "Only supplier portal users can create ASNs." | |
| 3-4 | As `supplier.a@test`, open `/app/scan-station` | **Not Permitted** page: "You are not permitted to access this page." | |

### 3.2 Single Material ASN: draft, edit, submit

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-5 | On `/asn_new`, set Purchase Order **PO-1**. Fill Supplier Invoice No `INV-A-001`, Invoice date, Invoice amount, Vehicle number `MH12AB1234`, Expected delivery, LR No/Date, Transporter, Driver contact. Under **Invoice Items** tick ITEM-A and ITEM-B (the Qty box starts empty) and type qty 60 and 50. Click **Save** | Redirects to `/asn/<name>` with a **Draft** indicator. **Edit** and **Submit** are offered. A draft has no Delete | |
| 3-6 | Start a new ASN on PO-1 but leave **Vehicle number** empty. Save | Under "Please fix the following errors:": "Vehicle Number is required." Form keeps what you typed. Nothing is saved | |
| 3-7 | New ASN: fill the header but leave **Supplier Invoice No** empty and tick **no items**. Save | Draft is saved and you stay on `/asn_new?asn_name=<name>`; the title shows the name and a Draft indicator | |
| 3-8 | On that draft set Supplier Invoice No to `INV-A-001` (used in 3-5). Save | "Supplier invoice number INV-A-001 is already used on another notice. Use a different number, or cancel that notice from your ASN list if it is still submitted and no purchase receipt has been created yet." | |
| 3-8a | Open the 3-7 draft from `/asn`, click **Edit**, tick ITEM-A with qty 1 and leave Supplier Invoice No empty. Save, then click **Submit** | Save works. Submit shows: "Supplier Invoice No is required." (Without an item, Submit shows "At least one item is required in the ASN" first) | |
| 3-9 | With PO-1 set and items ticked, set Purchase Order to PO-2 | Confirm "Changing purchase order will clear selected items and rows. Continue?" OK switches to PO-2 with no rows. Cancel keeps PO-1 | |
| 3-10 | Set PO-1, tick an item, then choose a Subcontracting Order | Confirm "Selecting a Subcontracting Order will clear the Purchase Order and its rows. Continue?" OK clears the PO. Setting a PO afterwards clears the Subcontracting Order | |
| 3-11 | New ASN on PO-1. Look at the Invoice Items list | ITEM-A shows "Remaining: 40" (the 3-5 draft holds back 60). ITEM-B is not listed (nothing left) | |
| 3-11a | Tick ITEM-A, qty **50**, fill the header with a new invoice no. Save | "Manual row 1: Row 1: qty 50.0 exceeds remaining PO qty 40.0." | |
| 3-12 | Tick ITEM-A again, or use **Select all filtered** | A PO line can be added only once; no second row appears | |
| 3-12a | Leave the page without saving. Open the 3-5 draft (its Rate boxes were left empty) | Each row shows the PO line rate | |
| 3-13 | Open the 3-5 draft, click **Edit**, change ITEM-A qty to 70, Save | Redirects to the detail page with ITEM-A 70 | |
| 3-14 | Click **Submit** on the 3-5 draft | Confirm dialog: "Submit this notice? Scan codes are created and the draft can no longer be edited." | |
| 3-15 | Confirm | Status **Submitted**. ASN date is today. **Scan codes** block shows a Barcode, a QR code, and the 16-character scan code label. **Edit** is gone | |
| 3-16 | Click **Copy scan code** | "Copied". Pasting gives the 16-character code | |
| 3-17 | Right-click the barcode image and open it in a new tab | URL is `/api/method/asn_module.qr_engine.generate.scan_image?code=...&kind=barcode` and shows a barcode PNG | |

Call the submitted ASN from 3-15 **ASN-M1** (ITEM-A 70, ITEM-B 50 on PO-1).

### 3.3 Cancel and delete from the portal

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-18 | Create and submit a new ASN on **PO-3**, ITEM-A 10, invoice `INV-A-DEL` | Submitted. **Cancel this notice** is offered | |
| 3-19 | Click **Cancel this notice** | Confirm "Cancel this shipping notice? This cannot be undone. You can submit a new notice with a different supplier invoice number if you need to replace it." OK returns to `/asn`; the row shows **Cancelled** and a **Delete** button. Opening the ASN shows **Delete this notice** | |
| 3-19a | Start a new ASN on PO-3 | ITEM-A shows "Remaining: 30" again: cancelling freed the qty | |
| 3-20 | Click **Delete this notice** | Confirm: "Permanently delete this cancelled notice? This cannot be undone." On confirm, back to `/asn` and the ASN is gone | |
| 3-21 | New ASN, header only (**no items**), invoice no `INV-A-DEL`. Save | Saved: a cancelled or deleted ASN does not hold its invoice number (despite what the cancel dialog says) | |
| 3-22 | On ASN-M1 after a Purchase Receipt exists for it (come back after 5-6) | **Cancel this notice** is not offered, on the detail page or the list row | |

### 3.4 Job ASN (Subcontracting Order)

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-23 | On `/asn_new`, leave Purchase Order empty and choose **SCO-1** under Subcontracting Order. Fill invoice `INV-A-JOB`, vehicle and amount. Leave Invoice Items unticked. Save | Redirects to `/asn/<name>` (Draft) with one line FG-JOB, qty 10: unticked, the order's remaining qty is shipped | |
| 3-23a | New ASN on SCO-1 with invoice `INV-A-JOB0`, tick FG-JOB and leave its Qty blank. Save | Saved with qty 0; you stay on the form as an incomplete draft | |
| 3-23b | Open the 3-23 draft, set a Purchase Order instead of the Subcontracting Order, Save | "ASN <name> is a Job ASN. Select its Subcontracting Order to save it." | |
| 3-24 | Submit it | Status **Submitted** with scan codes | |

Call it **ASN-J1**.

### 3.5 Bulk upload (portal)

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-25 | On `/asn_new` open the **Bulk ASN Upload** tab, click **Download CSV template** | `asn_bulk_upload_template.csv` downloads, header row only, with these headers in order: `supplier_invoice_no, supplier_invoice_date, expected_delivery_date, lr_no, lr_date, transporter_name, vehicle_number, driver_contact, supplier_invoice_amount, purchase_order, sr_no, item_code, qty, rate` | |
| 3-26 | Upload a CSV with a header renamed, a column missing or an extra column | Under "Bulk upload failed. No ASNs created.": "CSV headers must match exactly: ..." | |
| 3-26a | Upload a header-only CSV | "Upload a CSV with rows." | |
| 3-27 | Two rows with the same invoice number but different `vehicle_number` | "Row 3: vehicle_number mismatch for invoice X; expected 'A', found 'B'." (row numbers are CSV line numbers; the first data row is Row 2) | |
| 3-28 | Two rows of one invoice with the same `purchase_order` + `sr_no` | "Row N: duplicate purchase_order + sr_no in invoice group X." | |
| 3-29 | Rows of one invoice naming PO-2 and PO-3 | "Row N: invoice group X must contain a single Purchase Order. Expected PO-2, found PO-3." | |
| 3-29a | A row with `supplier_invoice_amount` blank | "Row 2: supplier_invoice_amount is required." | |
| 3-29b | A row with a wrong `sr_no`, then one with a wrong `item_code` | "Row N: No PO item found for PO X and sr_no Y." / "Row N: item_code A does not match PO line item_code B." | |
| 3-30 | A row whose qty exceeds the PO line's remaining qty | "Row N: qty X exceeds remaining PO qty Y." and "No ASNs created due to validation failures." | |
| 3-31 | Upload a valid CSV: invoice `INV-A-BULK1` on PO-2 ITEM-A 20, and invoice `INV-A-BULK2` on PO-2 ITEM-A 20 | "Your file passed validation. 2 ASN(s) are queued and will be created and submitted in the background. We will email you the result." | |
| 3-32 | Wait for the background job, then check `/asn` and the supplier's email | Two **Submitted** ASNs. Email "Bulk ASN upload finished": "Created and submitted 2 ASN(s): <names>" | |
| 3-33 | After the job has run, upload the same file again | For each invoice: "Supplier invoice number INV-A-BULK1 is already used on another notice. ..." | |

Sample valid CSV (replace PO name and Sr No with yours; Sr No is the PO line's row number):

```csv
supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate
INV-A-BULK1,2026-11-16,2026-11-18,LR-1,2026-11-16,Fast Freight,MH12AB1111,9800000001,2000,PUR-ORD-XXXX,1,ITEM-A,20,100
INV-A-BULK2,2026-11-16,2026-11-18,LR-2,2026-11-16,Fast Freight,MH12AB2222,9800000002,2000,PUR-ORD-XXXX,1,ITEM-A,20,100
```

### 3.6 Supplier isolation

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 3-34 | Log in as `supplier.b@test`. Open `/asn` | None of Supplier A's ASNs are listed | |
| 3-35 | Paste the URL of ASN-M1 (`/asn/<name>`) | **Page Not Found** (404). Nothing of ASN-M1 is shown | |
| 3-36 | On `/asn_new`, look at the Purchase Order picker | Only PO-B is offered (the supplier's submitted, non-subcontracted POs still To Receive). PO-1, PO-2, PO-3 are not | |

---

## 4. ASN on the desk

### 4.1 Create and validate

Log in as `stores.mgr@test`. Open **ASN > New**.

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 4-1 | Pick Supplier A. The new form starts with one empty Items row, so answer **Yes** to "Changing supplier will clear all items. Continue?". Add a row and open the Purchase Order picker | Picker shows Supplier A's submitted POs with status To Receive or To Receive and Bill. Unlike the portal, the subcontracting PO behind SCO-1 is also offered | |
| 4-2 | Choose **PO-3** in the row | The row fills from PO-3's line: Item Code, UOM and Rate read-only, Qty = remaining qty (30). A PO with more lines adds one row per line that has qty left; lines with nothing left are skipped | |
| 4-3 | Change the Supplier to Supplier B | Confirm "Changing supplier will clear all items. Continue?". **Yes** clears the rows and keeps Supplier B. **No** puts Supplier A back, but the same confirm then appears a second time; answer No again to keep the rows (known quirk, log it) | |
| 4-4 | With Supplier A, PO-3 row, Supplier Invoice No and Supplier Invoice Amount filled (both are mandatory even for a draft), Save without a Vehicle Number | "Vehicle Number is required." | |
| 4-5 | Add a PO-1 row (PO-1 still has ITEM-A 30 left) to the PO-3 ASN. Save | "An ASN can reference only one order." | |
| 4-6 | Remove the PO-1 row. Set ITEM-A qty to 31. Save | "Rows 1: Shipped qty 31.0 exceeds remaining PO qty 30.0" | |
| 4-7 | Type qty 0 in a row | "Quantity must be greater than 0" and Qty goes back to 1 | |
| 4-8 | Use Supplier Invoice No `INV-A-001`. Save | "Supplier Invoice No INV-A-001 already exists for Supplier Supplier A" | |
| 4-9 | Fix it: PO-3 ITEM-A 30, invoice `INV-A-DESK`, vehicle set. Save, then Submit | Status **Submitted**, ASN Date today, **Scan Code (manual entry)** filled, trace table shows ASN_GENERATED | |
| 4-10 | Log in as `stores.user@test`, create a draft ASN | Can save and delete the draft, but has no **Submit** button | |
| 4-11 | Log in as `accounts.user@test`, open an ASN | Read-only | |

Call the 4-9 ASN **ASN-M3**.

### 4.2 Trace on the form

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 4-12 | Open ASN-M1 | **Traceability** section with columns Item / State / Status / Ref / Updated: each item has **ASN_GENERATED**, status OK, Ref "ASN <name>" | |
| 4-13 | Click **Open Full Trace View** | **ASN Item Transition Trace** report opens filtered on this ASN | |

### 4.3 Notification

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 4-14 | After Supplier A submits an ASN on the portal, check `stores.mgr@test`'s bell notifications and the Email Queue | Both have "New ASN <name> submitted by <supplier>", body with "Expected delivery: <date>" and "Invoice: <no>". When stores.mgr submits it (4-9), only the email arrives: Frappe does not notify the user who did it | |

### 4.4 Desk bulk upload

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 4-15 | ASN list > **Bulk Upload ASN** > **Download Template** | `asn_bulk_upload_template.csv`, same headers as the portal | |
| 4-15a | Pick Supplier A, upload a CSV with one good row and one row over the remaining qty. **Create ASNs** | "Bulk Upload Failed" listing each row error, ending "No ASNs created due to validation failures." No ASN is created | |
| 4-15b | Upload a CSV naming PO-B (Supplier B's) with Supplier A selected | "Only open Purchase Orders can be selected. Invalid selections: PO-B" | |
| 4-16 | Upload a valid CSV (new invoice no; PO-2 has nothing left, so use PO-CAP ITEM-C 10) and click **Create ASNs** | Dialog "ASNs Created": "Created 1 ASN(s): <link>". Submitted at once, no email | |
| 4-17 | As `stores.user@test`, open Bulk Upload ASN (the button shows for everyone) and click **Download Template** or **Create ASNs** | "You need create and submit permission on ASN to use bulk upload." (titled "Download Failed" or "Bulk Upload Failed") | |

---

## 5. Scanning: Material ASN, Gate Pass Mode OFF

Confirm **ASN Settings > Gate Pass Mode** is off. Log in as `stores.user@test`.

How scanning behaves:
- **Ctrl+Shift+S dialog**: on success it takes you to the new or reopened document. Use it for every scan below unless the step says Scan Station.
- **Scan Station**: on success it stays on the page with a green alert "<message> <link>" and refreshes Recent Scans. Click the link to open the document.
- Refusals from the app (wrong status, voided code, guardrails) show in a message dialog, and on Scan Station also in the red box under the input.
- Failure rows in **Scan Log** are written by a background job, so they appear only while workers are running.

### 5.1 Scan tools

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 5-1 | Open `/app/scan-station` | **Scan Station** page: heading "Scan QR Code or Barcode", input "Scan here...", **Process Scan** button, **Recent Scans** list | |
| 5-2 | Anywhere in the desk press **Ctrl+Shift+S** | **Scan QR Code** dialog with "Scan or paste code" and **Process** | |
| 5-3 | Process an empty input in either tool | Nothing happens: no message, no request, no Scan Log row | |
| 5-4 | Paste `ABCDEFGHIJKLMNOP` into Scan Station | Submits by itself after a moment. Red box: "Unknown or invalid scan code." (or "Scan failed. Please try again." if System Settings > Allow Error Traceback is off). In the dialog the alert is "Scan failed. Check Scan Log for details." Scan Log gets a Failure row: Action `unknown`, Source DocType User, Source Name = your user | |
| 5-5 | Scan ASN-M1's QR code with a phone logged in to the desk as `stores.user@test` | Scan Station opens with the 16-character code in the input. Nothing is processed until you press Process Scan. Don't press it; 5-6 does the scan | |

### 5.2 ASN to Purchase Receipt to Purchase Invoice

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 5-6 | Scan ASN-M1's code | "Purchase Receipt <PR> created from ASN ASN-M1". Draft receipt: Supplier A, PO-1 lines ITEM-A 70 and ITEM-B 50, **ASN** = ASN-M1, Supplier Delivery Note = INV-A-001, Vehicle No, Transporter and LR No/Date from the ASN | |
| 5-7 | Scan ASN-M1 again | "Existing draft Purchase Receipt <PR> opened": no second receipt | |
| 5-7a | On the draft, open the ITEM-A row, **Duplicate** it, Submit | The copy lands as row 2: "Row 2: ASN ASN-M1 has no qty left for ITEM-A, so the row's 70.0 would be received over what was shipped. Remove row 2." Remove the copy | |
| 5-8 | Check **Scan Log** and **Scan Code** for ASN-M1 | Scan Log has a Success row per scan. Scan Code status **Used**, Scan Count 2 | |
| 5-9 | Submit the Purchase Receipt (full qty) | ASN-M1 **Received**. Each ASN Item has Received Qty = Shipped Qty, Discrepancy Qty 0 | |
| 5-10 | Check `accounts.user@test`'s bell notifications | "Purchase Receipt <name> ready for billing" | |
| 5-11 | Print the receipt with format **Purchase Receipt Scan Code** | Prints the barcode of the receipt's Scan Code only | |
| 5-12 | Scan ASN-M1 once more | "Cannot create Purchase Receipt from ASN ASN-M1 with status Received" | |
| 5-13 | As `stores.user@test`, scan the Purchase Receipt's code | Dialog "Not permitted": "You do not have enough permissions to access this resource. Please contact your manager to get access." Scan Log Failure row: "You do not have permission to perform this action. Required roles: Accounts User, Accounts Manager" | |
| 5-14 | As `accounts.user@test`, scan the Purchase Receipt's code | "Purchase Invoice <PI> created from Purchase Receipt <PR>". Draft invoice with ASN = ASN-M1 and Supplier Invoice No/Date from the ASN | |
| 5-15 | Scan the receipt code again | "Existing Purchase Invoice <PI> opened" | |
| 5-16 | Submit the Purchase Invoice. Scan the receipt code again | Submitted. Trace shows PI_CREATED_DRAFT (from 5-14); submitting adds no trace row. The scan says "Existing Purchase Invoice <PI> opened" | |
| 5-17 | Open the receipt | No **Create > Purchase Invoice**: it is fully billed | |
| 5-17a | As `accounts.user@test`, cancel the 5-16 invoice. Click **Amend** on it twice so two drafts exist (PI-1-1, PI-1-2), both with ASN = ASN-M1. Submit PI-1-1, then PI-1-2. Afterwards cancel and delete PI-1-2's draft if it remains | PI-1-2 refused: "ASN ASN-M1 is already fully invoiced on Purchase Invoice PI-1-1. Cancel PI-1-1 to invoice it again." | |
| 5-17b | Scan the receipt code once more | "This scan code has already been used and cannot be scanned again." (the invoice it made was cancelled; known limit) | |
| 5-17c | Make a **Purchase Return** for 5 ITEM-A against the 5-9 receipt and submit | ASN-M1 stays **Received**, Received Qty unchanged | |

### 5.3 Short receipt closes the ASN

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 5-18 | Scan ASN-M3 (PO-3 ITEM-A 30). On the draft receipt change qty to **25**. Submit | ASN-M3 **Closed**. Received Qty 25, Discrepancy Qty 5 | |
| 5-18a | Supplier A starts a new ASN on PO-3 (do not save) | ITEM-A shows "Remaining: 5": a Closed ASN frees what it did not deliver | |
| 5-19 | Scan ASN-M3 again | "Cannot create Purchase Receipt from ASN ASN-M3 with status Closed" | |
| 5-20 | Cancel that Purchase Receipt | ASN-M3 back to **Submitted**, Received Qty 0, Discrepancy Qty 30. Trace shows **PR_CANCELLED** | |
| 5-21 | As `accounts.user@test`, scan the cancelled receipt's code | "This scan code is not valid for scanning." (title "Scan not allowed") | |
| 5-22 | Scan ASN-M3 and submit the new draft receipt with full 30 | "Purchase Receipt <PR> created from ASN ASN-M3". After submit, ASN-M3 **Received** | |

### 5.4 Cancel an ASN at the desk

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 5-23 | Create and submit an ASN on PO-CAP ITEM-C 5 (`INV-A-CXL`). Scan it so a draft receipt exists | Draft receipt created | |
| 5-24 | As `stores.mgr@test`, cancel that ASN. Then scan its code | ASN **Cancelled**, draft receipt deleted. Scan: "Unknown or invalid scan code." (the code row is gone) | |
| 5-25 | As `stores.mgr@test`, click Cancel on ASN-M1 | Dialog **Cancel All Documents**: "ASN ASN-M1 is linked with the following submitted documents: Purchase Receipt: <PR>, Purchase Invoice: <PI>" then "You do not have permissions to cancel all linked documents." No Cancel All button. Closing it leaves ASN-M1 Received. **Do not run this as Administrator**: Administrator gets Cancel All, which cancels the invoice, the receipt and the ASN | |

---

## 6. Receipt guardrails

These check that goods declared on an ASN are received through the ASN. First cancel the 4-16 ASN (PO-CAP ITEM-C 10) so only ASN-G1 is open on PO-CAP.

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 6-1 | Supplier A submits an ASN on PO-CAP ITEM-C 50 (`INV-A-G1`). Call it **ASN-G1** | Submitted | |
| 6-2 | As `stores.user@test`, make a Purchase Receipt **from PO-CAP directly** (Create > Purchase Receipt), no ASN, ITEM-C 200. Submit | Title "Quantity Declared on an Open ASN": "Row 1: 50.0 of ITEM-C on <PO-CAP> row 1 is already declared on ASN-G1; receive it by scanning ASN-G1" | |
| 6-3 | Change that receipt to ITEM-C 150 and submit. Then cancel it | Submits: 150 is the part no open ASN covers | |
| 6-4 | As `accounts.user@test`, make a Purchase Invoice from PO-CAP with **Update Stock** ticked, ITEM-C 200. Submit, then delete the draft | Same refusal as 6-2 | |
| 6-5 | Scan ASN-G1, submit PR-1 (ASN-G1 Received). Cancel PR-1 (back to Submitted). Scan ASN-G1 again: PR-2 is created. Open PR-1 and click **Amend** (PR-1-1 carries ASN-G1). Submit PR-2, then PR-1-1. Delete PR-1-1 afterwards | PR-1-1 refused: "ASN ASN-G1 is already Received, booked on Purchase Receipt PR-2. Cancel that document to book the ASN again." | |
| 6-6 | Supplier A starts a new ASN on PO-1 and looks for ITEM-B | ITEM-B is not offered: all 50 were shipped | |

### 6.1 Over-receipt allowance

Use **PO-ALW** (ITEM-A 100). Do these on the desk as `stores.mgr@test`, and delete each draft after saving it.

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 6-7 | Set **Stock Settings > Over Delivery/Receipt Allowance** to 10% (ITEM-A's own allowance 0). ASN on PO-ALW ITEM-A 110. Save, then delete it | Saves | |
| 6-8 | Same with qty 111 | "Rows 1: Shipped qty 111.0 exceeds remaining PO qty 110.0" | |
| 6-9 | Set ITEM-A's own Over Delivery/Receipt Allowance to 5%. Try qty 106 | "Rows 1: Shipped qty 106.0 exceeds remaining PO qty 105.0" (the Item's value wins). Set both allowances back to 0 | |

---

## 7. Gate Pass Mode ON (Material)

Needs S-3, plus:
- `stores.user@test` can create, submit and cancel Gate Pass. On staging this comes from Custom DocPerm: Stock User has full rights, Stock Manager none.
- Gate Pass Type records **Material** and **Job** exist.
- The ASN has a **Supplier Invoice Date**. Gate In makes Invoice Number, Invoice Date and Challan Number mandatory in the form. A scan saves without them, but submitting the Gate Pass from the form will ask for Invoice Date if the ASN has none.
- The Gate Pass reference on the Purchase Receipt appears only if the site has the field `custom_gate_pass_reference` (staging and production have it).
- Scanning needs Stock User or Stock Manager. A user with only the **Gate Entry** role can make Gate Passes but cannot scan.

What the site's own Gate Pass scripts add (checked on staging, 2026-11-16):
- The client script "Gate Pass With Conversion Factor" locks a Gate Pass built from an ASN scan: **Get Items** is hidden, and both tables lose Add Row, Insert and Duplicate. Rows can only come from the ASN.
- The Before Save server script "Gate Pass" copies the supplier from the Purchase Order and refuses a fulfilled or closed PO. It also requires the Invoice Number to be unique per supplier across non-cancelled Gate Passes, and Receive Qty ≤ Pending Qty on each Purchase Order Items row. These run on the save a scan does, so they can refuse a scan.

As System Manager turn **ASN Settings > Gate Pass Mode** on.

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 7-1 | Supplier A submits an ASN on **PO-4** (ITEM-A 20, ITEM-B 10), vehicle `MH12GP0001`, invoice `INV-A-GP1`. Call it **ASN-GP1** | Submitted | |
| 7-2 | As `stores.user@test`, scan ASN-GP1 | "Gate Pass <GP> created from ASN ASN-GP1". Draft Gate Pass: Entry Type Gate In, Gate Pass Type Material, Document Reference Purchase Order, Reference Number PO-4, Company, Supplier A, vehicle, Invoice Number/Date and Challan Number/Date = the supplier invoice, ASN = ASN-GP1. Rows in the **Purchase Order Items** table: Qty (PO line qty), Receive Qty = Shipped Qty (Pending Qty is hidden); ASN Item visible when you open a row | |
| 7-3 | Scan ASN-GP1 again | "Existing Gate Pass <GP> opened" | |
| 7-4 | Look at the form and open row 1 | No **Get Items** button. No Add Row under either table. The row form has no Duplicate, Insert Above or Insert Below. (The server also refuses two rows on one ASN line, "Gate Pass rows 1 and 2 are both on ASN Item <ID>. Remove row 2.", but only an API or import save can get there) | |
| 7-5 | Submit. Print with **Gate Pass Scan Code** | Submitted; the Scan Code field is filled. The print shows the barcode only | |
| 7-6 | Scan the Gate Pass code | "Purchase Receipt <PR> created from Gate Pass <GP>". Qty from each row's Receive Qty, ASN = ASN-GP1 | |
| 7-7 | Scan the Gate Pass code again | "Existing Purchase Receipt <PR> opened" | |
| 7-7a | Reload the Gate Pass | The **Create** menu is gone; a **Purchase Receipt** group holds a button named after the 7-6 receipt | |
| 7-8 | Submit the receipt | ASN-GP1 **Received**. The receipt code works for the invoice as in 5-14 | |
| 7-8a | As `accounts.user@test`, scan the Gate Pass code | Refused: Gate Pass codes need Stock User or Stock Manager | |
| 7-9 | Submit **ASN-GP2** on **PO-5**. Scan it, submit the Gate Pass, then cancel the Gate Pass. Scan the Gate Pass code | "This scan code is not valid for scanning." (title "Scan not allowed") | |
| 7-10 | Scan ASN-GP2 again | "Gate Pass <new GP> created from ASN ASN-GP2": the cancelled one is ignored | |
| 7-11 | On the 7-10 draft, set ITEM-B Receive Qty to 0. Submit, scan its code, submit the receipt | The receipt has no ITEM-B row. ASN-GP2 **Closed**, ITEM-B Discrepancy Qty 10 | |
| 7-12 | With mode on, submit **ASN-GP3** on **PO-6** and scan it (draft Gate Pass). Turn mode **off** and scan ASN-GP3 | "Purchase Receipt <PR> created from ASN ASN-GP3", built from the shipped qty. The draft Gate Pass is left as it is | |
| 7-12a | Turn mode back on and scan ASN-GP3 | "Existing draft Purchase Receipt <PR> opened": no Gate Pass is used while a draft receipt exists | |
| 7-13 | Submit **ASN-GP4** on **PO-7** and scan it. Submit the Gate Pass, but instead of scanning its code use **Create > Purchase Receipt** on the Gate Pass. Save the receipt | The receipt opens unsaved with the Receive Qty. On save its **ASN** field is set to ASN-GP4 (stamped from the Gate Pass). Submit: ASN-GP4 **Received** | |
| 7-14 | As `stores.user@test`, make a Gate Pass by hand: Gate In, Material, Purchase Order **PO-8**, Invoice Number `INV-A-GP9`. Save it. Then Supplier A submits an ASN on PO-8 with invoice `INV-A-GP9`. Scan it | Refused by the site's script: "Invoice Number 'INV-A-GP9' already exists for supplier '<Supplier A ID>' in Gate Pass '<manual GP>'." Cancel or delete the manual Gate Pass and the scan works | |
| 7-15 | Set Stock Settings over-receipt allowance to 10%. Supplier A submits an ASN on **PO-9** with ITEM-A 105. Scan it. Set the allowance back to 0 | The ASN is accepted, but the scan is refused by the site's script: "Excess quantity for item ITEM-A. Receive Qty (105.0) > Pending Qty (100.0)". In Gate Pass Mode the allowance cannot be used | |

Turn Gate Pass Mode off afterwards.

Known limit: once the invoice or receipt a code created is cancelled, scanning that code again gives "This scan code has already been used and cannot be scanned again." Make the next document by hand.

---

## 8. Subcontracting (Job) flow

Gate Pass Mode **off** unless stated. The Subcontracting Order, Stock Entry and Subcontracting Receipt have no barcode print format: copy the document's read-only **Scan Code** field into Scan Station.

### 8.1 Order to dispatch to receipt

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 8-1 | Open the submitted **SCO-1** | A read-only **Scan Code** field after Supplier, filled on submit | |
| 8-2 | Scan SCO-1's code | "Stock Entry <SE> (Send to Subcontractor) created from SCO-1". A draft Stock Entry opens, purpose Send to Subcontractor, linked to SCO-1, RM-JOB lines at the BOM qty for 10 | |
| 8-2a | Scan SCO-1's code again | "Existing Stock Entry <SE> opened": the same draft | |
| 8-3 | Submit the Stock Entry (RM-JOB must be in stock) | Its read-only **Scan Code** field (after Subcontracting Order) is filled | |
| 8-4 | Scan the Stock Entry code | "Subcontracting Receipt <SCR> created from SCO-1" (names the order, not the Stock Entry). The draft has SCO-1's full pending FG-JOB qty and **no ASN link**. **Delete this draft** before 8.2 | |
| 8-5 | On SCO-1 make a second Send to Subcontractor Stock Entry by hand (small qty), submit it, then cancel it. Scan its code. (Do not cancel the 8-3 entry: 8-8 needs its raw material at the supplier) | "This scan code is not valid for scanning." (title "Scan not allowed") | |
| 8-5a | Make and submit a throwaway Subcontracting Order (no Stock Entry), cancel it, scan its code | "This scan code is not valid for scanning." | |

### 8.2 Job ASN to Subcontracting Receipt to Purchase Receipt

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 8-6 | Scan **ASN-J1** (from 3-24) | "Subcontracting Receipt <SCR> created from ASN ASN-J1". Draft with FG-JOB qty 10 (the Shipped Qty), process loss 0, ASN = ASN-J1 | |
| 8-7 | Scan ASN-J1 again | "Existing draft Subcontracting Receipt <SCR> opened" | |
| 8-8 | Submit the Subcontracting Receipt | ASN-J1 **Received**. The receipt's **Scan Code** field is filled | |
| 8-8a | Scan ASN-J1 again | "Cannot create Subcontracting Receipt from ASN ASN-J1 with status Received" | |
| 8-9 | Scan the Subcontracting Receipt code | "Purchase Receipt <PR> created from Subcontracting Receipt <SCR>". Draft for the subcontracting PO: line is the service item **SVC-JOB** (not FG-JOB), qty from the FG qty, Subcontracting Receipt = <SCR>, no ASN. (If Buying Settings > Auto Create Purchase Receipt is ticked, the receipt submit already made the draft, and the scan says "Existing draft Purchase Receipt <PR> opened") | |
| 8-10 | Submit it, then scan its code as `accounts.user@test` | Draft **Purchase Invoice** from the Purchase Receipt | |
| 8-11 | On the submitted Subcontracting Receipt open **Create** | Only Purchase Receipt (and Subcontract Return) are offered, no Purchase Invoice. Its Scan Code opens a Purchase Receipt, never an invoice | |
| 8-12 | Delete the 8-10 draft invoice, cancel the 8-10 Purchase Receipt, then cancel the Subcontracting Receipt | ASN-J1 goes back to **Submitted** | |
| 8-13 | Scan ASN-J1, set FG-JOB to **8** on the draft receipt, submit | ASN-J1 **Closed**, Received Qty 8 | |
| 8-14 | On that receipt: **Create > Subcontract Return**, submit | The return's Scan Code stays empty: there is nothing to scan. ASN-J1 stays **Closed**, Received Qty unchanged | |

### 8.3 Job ASN with Gate Pass Mode ON

Needs S-3 and **SCO-2** with its raw material sent to the supplier (Send to Subcontractor submitted).

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 8-15 | Turn Gate Pass Mode on. On the portal, Supplier A submits a Job ASN on SCO-2 (**ASN-J2**). Scan it | "Gate Pass <GP> created from ASN ASN-J2". Draft Gate Pass: Entry Type Gate In, Gate Pass Type Job, Document Reference Subcontracting Order, Reference Number SCO-2, Company, Supplier A, vehicle, Invoice No/Date and Challan No/Date = the supplier invoice, ASN = ASN-J2. Lines are in the **Items** table (fieldname `item`), not **Purchase Order Items**: FG-JOB, Subcontracting Order Item, Qty = Shipped Qty (Pending Qty is hidden). Get Items is hidden and rows cannot be added | |
| 8-15a | Scan ASN-J2 again | "Existing Gate Pass <GP> opened" | |
| 8-16 | Fill any fields your site's Gate Pass marks mandatory, submit it, scan its code | "Subcontracting Receipt <SCR> created from ASN ASN-J2" (names the ASN). Qty from the Gate Pass line, ASN = ASN-J2 | |
| 8-16a | Scan the Gate Pass code again | "Existing Subcontracting Receipt <SCR> opened" | |
| 8-17 | Submit the Subcontracting Receipt, then scan the Gate Pass code | ASN-J2 **Received**. The scan creates nothing new: it opens the submitted receipt with "Existing Subcontracting Receipt <name> opened" | |

Turn Gate Pass Mode off afterwards.

---

## 9. Stock Cap

### 9.1 Setup and validation

As `stores.mgr@test`.

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 9-1 | New **ASN Stock Cap Settings**: Branch North, warehouse **Stores - N**. Save | Saved, named after the branch, Enabled ticked by default | |
| 9-2 | Add a group warehouse (e.g. All Warehouses) as row 2. Save | "Row 2: All Warehouses - <abbr> is a group warehouse. Stock is only recorded against leaf warehouses, so a group would never count toward the cap. List its leaves instead." | |
| 9-3 | Add Stores - N again as row 2. Save | "Row 2: Stores - N is listed twice." | |
| 9-4 | New settings for Branch South listing Stores - N | "Warehouse Stores - N is already a cap warehouse for branch Branch North. A warehouse can belong to only one branch." | |
| 9-5 | New **ASN Item Branch Cap**: ITEM-C, Branch North, Max Qty **100** | Saved, no warning | |
| 9-6 | Set Max Qty to -1 | "Max Qty cannot be negative." | |
| 9-7 | As `stores.user@test`, open both doctypes | Read-only | |

### 9.2 Enforcement

Before you start:
- Open ITEM-C ASNs: the 4-16 ASN was cancelled at the start of section 6 and the 5-23 ASN in 5-24. ASN-G1 (6-1) is Received after 6-5, so it no longer counts.
- In Transit counts only **submitted** ASNs that are not Received or Closed. Drafts never count.
- ITEM-C on hand in Stores - N is 50 after 6-5. Bring it to **60** with a Stock Reconciliation.
- Gate Pass Mode off.

Figures in desk messages print with one decimal (110.0).

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 9-8 | Desk: ASN on PO-CAP ITEM-C **50**. Save | Saves with an orange **Stock Cap Warning**: "Item ITEM-C in branch Branch North (rows 1): projected stock 110.0 exceeds maximum 100.0. On hand 60.0, in transit 0.0, this document 50.0." | |
| 9-8a | Add 30 ITEM-C to **Stores - S** (not a cap warehouse) and save the ASN again | Same warning: On hand still 60.0 | |
| 9-9 | Submit it | Blocked, title **Stock Cap Exceeded**, same text as 9-8 | |
| 9-10 | Change qty to **40** and submit | Submitted: projected 100.0 equals the maximum, which is allowed | |
| 9-11 | Portal: Supplier A saves an ASN on PO-CAP ITEM-C 10, then clicks **Submit** | Save works. Submit is refused with no figures: "Item ITEM-C (rows 1): the branch already has as much of this item as it can take. You cannot declare any more." | |
| 9-12 | Raise Max Qty to 120. On the portal, edit the 9-11 draft to ITEM-C 30 and Submit | "Item ITEM-C (rows 1): the branch cannot take this quantity. You may declare at most 20." (60 on hand + 40 in transit; the draft does not count) | |
| 9-13 | Portal bulk CSV with two invoices on PO-CAP, ITEM-C 15 each | The whole file is refused, nothing is queued: "Bulk upload failed. No ASNs created.", then "Invoice <2nd invoice>: Row 3: Item ITEM-C (rows 3): the branch cannot take this quantity. You may declare at most 5." and "No ASNs created due to validation failures." | |
| 9-14 | Set Max Qty to **0**. Desk: new ASN on PO-CAP ITEM-C 100. Save (do not submit), then delete it | No Stock Cap Warning: 0 means uncapped | |
| 9-15 | Untick **Enabled** on the Branch North settings. Set Max Qty back to 100 and save | Orange **Cap Not Yet Enforced**: "Branch Branch North has no enabled ASN Stock Cap Settings, so this limit will not be enforced until its cap warehouses are configured." | |
| 9-15a | Desk ASN on PO-CAP ITEM-C 60. Save (do not submit), then delete it | No Stock Cap Warning | |
| 9-16 | Re-enable the settings. Raise ITEM-C on hand in Stores - N to 80 with a Stock Reconciliation (not checked by the cap). Scan the 40-qty ASN from 9-10 and submit its Purchase Receipt | Blocked, **Stock Cap Exceeded**: "Item ITEM-C in branch Branch North (rows 1): projected stock 120.0 exceeds maximum 100.0. On hand 80.0, in transit 0.0, this document 40.0." (the receipt's own 40 is taken off in transit) | |
| 9-17 | Optional, Job ASN: cap FG-JOB in Branch North (SCO line warehouse Stores - N). Submit a Job ASN over the cap, then one exactly at it | The first is blocked on submit, the second submits | |

Note: the cap reads stock without locking, and Stock Entry, Stock Reconciliation and transfers are not checked. Stock above the cap after those is expected, not a bug (ADR 0001).

---

## 10. Reports and logs

| # | Steps | Expected | Result |
|---|-------|----------|--------|
| 10-1 | **ASN Item Transition Trace**, filter ASN = ASN-M1 | Per ASN item, newest first: PI_CREATED_DRAFT (Purchase Invoice), PR_SUBMITTED, PR_CREATED_DRAFT (Purchase Receipt), ASN_GENERATED (ASN), all Status OK. Columns: Event Time, ASN, ASN Item, Item Code, State, Status, Reference, Actor, Error Code, Details. With Gate Pass Mode on, GATE_PASS_SUBMITTED and GATE_PASS_CREATED_DRAFT (Gate Pass) also appear between PR_CREATED_DRAFT and ASN_GENERATED, and GATE_PASS_CANCELLED if the pass was cancelled. There is no state for a submitted invoice. The DRAFT states appear only when the document was made by scanning | |
| 10-2 | Try each filter: Item Code, State, Status, Ref DocType, Ref Name, From/To Date, Search, Page limit | State and Status match exact values. Search matches part of State / Item Code / Ref Name / Details | |
| 10-2a | Clear ASN and From Date, then use Search | "Set ASN or From Date to use Search." | |
| 10-3 | **ASN Item Rate Difference** with no filters | "Set at least one filter (ASN, Supplier, Purchase Order, Invoice No or date)." | |
| 10-4 | Create an ASN by bulk CSV with `rate` 110 on a PO line priced 100 (the desk form cannot change Rate). Run the report for that ASN | ASN Rate 110, PO Rate 100, Rate Difference 10, Qty, Amount Difference = qty × 10. Draft ASNs are included too | |
| 10-5 | Run 10-4 as `accounts.user@test`, Purchase Order filter empty (Accounts User has no PO read) | Works | |
| 10-6 | Give `accounts.user@test` a User Permission on Supplier = Supplier B. Run the report with Supplier A typed in full (the picker will not offer it) | No rows. Note: the Transition Trace report does not apply User Permissions, so this user still sees Supplier A's trace rows there | |
| 10-7 | **Scan Log** list | One SCAN-#### row per scan (no list columns). Open a row or use Report view: Scan Timestamp, User, Action, Source DocType/Name, Scan Code, Result (Success/Failure), Result DocType/Name, Error Message. Read-only, no New button | |

---

## 11. Permission summary

Tick each cell after you have tried it.

| Action | Supplier (portal) | Stock User | Stock Manager | Accounts User |
|--------|-------------------|------------|---------------|---------------|
| Create / edit own draft ASN on portal | Yes | n/a | n/a | n/a |
| See other suppliers' ASNs | No | Yes (all ASNs) | Yes (all ASNs) | Yes (all ASNs) |
| Create ASN on desk | n/a | Yes | Yes | No |
| Submit / cancel ASN on desk | n/a | No | Yes | No |
| Desk bulk upload | n/a | No | Yes | No |
| Scan ASN / Gate Pass / SCO / Stock Entry / SCR codes | No ("Only desk users can scan codes.") | Yes | Yes, only with Stock User too (needs PO / SCO read) | No |
| Scan Purchase Receipt code (make invoice) | No | No | No | Yes |
| Edit Stock Cap settings and caps | No | Read | Yes | No |
| Edit ASN Settings | No | No | No | No (System Manager only) |
| Run Rate Difference report | No | No | Yes | Yes |
| Run Transition Trace report | No | Yes | Yes | Yes |

---

## 12. Status reference

| ASN status | When |
|------------|------|
| Draft | Saved, not submitted |
| Submitted | Submitted, nothing received yet (also after its receipt is cancelled) |
| Received | Its receipt covered every line in full |
| Closed | Its receipt was short on any line. No further receipt is taken, and the unreceived qty goes back to the PO's Remaining Qty |
| Cancelled | Cancelled by the supplier or a Stock Manager |
| Partially Received | In the options list but never set by the app. Fail if you ever see it |

---

## 13. Sign-off

| Section | Pass | Fail | Blocked | Notes |
|---------|------|------|---------|-------|
| 2 Settings | | | | |
| 3 Supplier portal | | | | |
| 4 Desk ASN | | | | |
| 5 Scanning (mode off) | | | | |
| 6 Guardrails | | | | |
| 7 Gate Pass Mode | | | | |
| 8 Subcontracting | | | | |
| 9 Stock Cap | | | | |
| 10 Reports | | | | |
| 11 Permissions | | | | |

Tested by: ____________ Approved by: ____________ Date: ____________
