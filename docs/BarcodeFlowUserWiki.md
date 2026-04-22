# Barcode Process Flow Wiki (User Guide)

This wiki shows one complete setup using the new one-screen model.

## Use Case

Target process:

`ASN -> Purchase Receipt -> (Purchase Invoice / Putaway)`

Branching rule:
- If **any item** has `inspection_required_before_purchase = 1`, use `Quality Inspection` route before stock movement.

## Step 1: Create Rules

Create `Barcode Rule`:
- `rule_name`: `any_item_requires_inspection`
- `scope`: `items_any`
- `field_path`: `items[].inspection_required_before_purchase`
- `operator`: `=`
- `value`: `1`
- `is_active`: checked

## Step 2: Create Mapping Sets

### Mapping Set: `ASN_to_PR`
Rows:
- `source_selector=supplier` -> `target_selector=supplier`
- `source_selector=supplier_invoice_no` -> `target_selector=supplier_delivery_note`
- `source_selector=items[].item_code` -> `target_selector=items[].item_code`
- `source_selector=items[].qty` -> `target_selector=items[].qty`
- `source_selector=items[].uom` -> `target_selector=items[].uom`

### Mapping Set: `PR_to_PI`
Use a standard handler path where possible. If custom fields are needed, add mapping rows similarly.

## Step 3: Create Barcode Process Flow

Create `Barcode Process Flow`:
- `flow_name`: `Inbound::PR::InvoiceAndTransfer`
- `is_active`: checked
- optional filters as needed (`company`, `warehouse`, `supplier_type`)

Add `Flow Step` rows:

1. `ASN -> Purchase Receipt`
- `from_doctype`: `ASN`
- `to_doctype`: `Purchase Receipt`
- `scan_action_key`: `asn_to_pr`
- `execution_mode`: `Mapping`
- `mapping_set`: `ASN_to_PR`
- `priority`: `100`
- `generate_next_barcode`: checked
- `generation_mode`: `hybrid`
- `is_active`: checked

2. `Purchase Receipt -> Purchase Invoice`
- `from_doctype`: `Purchase Receipt`
- `to_doctype`: `Purchase Invoice`
- `scan_action_key`: `pr_to_pi`
- `execution_mode`: `Mapping` (or `Server Script` if required)
- `mapping_set`: `PR_to_PI`
- `priority`: `100`
- `generate_next_barcode`: checked
- `generation_mode`: `hybrid`
- `is_active`: checked

3. `Purchase Receipt -> Quality Inspection` (conditional branch)
- `from_doctype`: `Purchase Receipt`
- `to_doctype`: `Quality Inspection`
- `scan_action_key`: `pr_to_qi`
- `execution_mode`: `Mapping` or standard handler
- `condition`: `any_item_requires_inspection`
- `priority`: `110` (higher than direct path if you want inspection-first)
- `generate_next_barcode`: checked
- `generation_mode`: `hybrid`
- `is_active`: checked

4. `Quality Inspection -> Stock Entry` (accepted path)
- `from_doctype`: `Quality Inspection`
- `to_doctype`: `Stock Entry`
- `scan_action_key`: `qi_to_transfer`
- `execution_mode`: `Mapping` or standard handler
- `priority`: `100`
- `is_active`: checked

## Step 4: Generate Initial Barcode

Create scan code for the first step key (`asn_to_pr`) against the ASN document.
That barcode drives the full chain because downstream barcodes are generated automatically from step settings.

## Step 5: Validate

1. Scan ASN barcode.
2. Confirm `Purchase Receipt` is created.
3. Confirm `Scan Log` has:
- `Barcode Process Flow`
- `Flow Step`
- `Flow Step Name`
4. If condition matched, confirm inspection branch barcode is generated.
5. Scan downstream barcodes and confirm created docs.

## Notes

- For custom docs (for example Gate Pass), set `from_doctype` / `to_doctype` directly and use mapping or server script mode.
- Branching is just multiple `Flow Step` rows with same `from_doctype`.
- Higher `priority` wins when multiple rows are eligible.
