# Barcode Process Flow Configuration Guide

This guide documents the **one-screen hard-cut model**.

## What Changed

- Old `Barcode Flow *` graph doctypes are removed.
- `QR Action Registry` / `QR Action Definition` are removed.
- Runtime now reads only:
  - `Barcode Process Flow`
  - child table `Flow Step`
  - `Barcode Rule`
  - `Barcode Mapping Set` + `Barcode Mapping Row`

## Authoring Order

1. Create `Barcode Rule` records (only if branching conditions are needed).
2. Create `Barcode Mapping Set` records.
3. Create one `Barcode Process Flow` record.
4. Add `Flow Step` rows directly in that flow.

## Barcode Process Flow Header

Required:
- `flow_name`
- `is_active`

Optional context filters:
- `company`
- `warehouse`
- `supplier_type`

If header filters are empty, the flow is global for matching source documents.

## Flow Step Row

Each row is one transition.

Required core fields:
- `from_doctype`
- `to_doctype`
- `execution_mode`

Execution modes:
- `Mapping`: requires `mapping_set`
- `Server Script`: requires `server_script`

Optional controls:
- `condition` (`Barcode Rule`)
- `priority` (higher wins)
- `scan_action_key` (stable action key for scan tokens)
- `generate_next_barcode`
- `generation_mode` (`immediate`, `runtime`, `hybrid`)
- `is_active`

## Rules

`Barcode Rule` supports:
- `header`
- `items_any`
- `items_all`
- `items_aggregate` with `exists`, `count`, `sum`, `min`, `max`, `avg`

## Mapping

`Barcode Mapping Set.rows` supports:
- `mapping_type`: `source` or `constant`
- `source_selector` examples: `supplier`, `header.company`, `items[].item_code`
- `target_selector` examples: `supplier`, `items[].item_code`
- optional `transform`: `upper`, `lower`, `int`, `float`, `str`

## Runtime Behavior

On scan:
1. Resolve source document from `Scan Code`.
2. Fetch active `Flow Step` rows where `from_doctype == source.doctype` and context matches.
3. Filter by `scan_action_key` from token.
4. Evaluate step condition (if configured).
5. Pick top-priority winner set.
6. Execute each winner.
7. Log flow + step in `Scan Log`.
8. Pre-generate next-step barcodes when enabled.

## Compatibility Notes

- Capability matrix supports ERPNext v15 and v16.
- v16-only `Material Request(Subcontracting) -> Purchase Order` templates are hidden in v15.

## Hard-Cut Policy

- No migration of old graph records.
- Reconfigure flows using `Barcode Process Flow`.
