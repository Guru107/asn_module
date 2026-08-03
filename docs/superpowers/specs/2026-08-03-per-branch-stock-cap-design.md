# Per-Branch Stock Cap — Design

**Status:** approved, not yet implemented
**Date:** 2026-08-03
**Supersedes part of:** [2026-07-28-asn-branch-stock-cap-design.md](2026-07-28-asn-branch-stock-cap-design.md)
**Depends on:** PR #26 (branch-wise stock cap) being merged first

## Problem

The stock cap ships one ceiling per item — `Item.custom_max_stock` — applied to every branch alike. Branches differ in size and role, so a single number is wrong for all but one of them. A limit of 200 that suits a main store is far too high for a satellite site and far too low for a hub.

The ceiling must vary per branch.

## Decision summary

| Question | Decision |
| --- | --- |
| What is the ceiling keyed by? | `(item, branch)` — one ceiling per branch |
| Is stock still pooled across a branch's warehouses? | Yes, unchanged |
| Where does the ceiling live? | New standalone doctype `ASN Item Branch Cap` |
| What happens to `Item.custom_max_stock`? | Retired — branch rows are the only source |
| Are existing values migrated? | No; the field and its values are deleted |
| What does `max_qty = 0` mean? | Uncapped, same as no row |
| Is misconfiguration signalled? | Yes — non-blocking warning when saving a cap row for an unconfigured branch |

**Explicitly not doing:** per-warehouse ceilings. A branch's warehouses continue to pool into one figure judged against one branch ceiling. Warehouse-level limits were considered and rejected as more granularity than the problem needs; the warehouse table keeps its single job of saying *which* stock counts.

## Data model

### New: `ASN Item Branch Cap`

| Field | Type | Constraints |
| --- | --- | --- |
| `item` | Link → Item | required |
| `branch` | Link → Branch | required |
| `max_qty` | Float | non-negative |

- **Naming:** `autoname: format:{branch}::{item}`. The document name *is* the composite key, so uniqueness is enforced by the primary key rather than a validate-time check that two concurrent saves could both pass. `::` is used because neither Branch names nor Item codes conventionally contain it; `validate()` additionally rejects a branch or item containing `::` so a crafted name cannot collide two distinct pairs onto one record.
- **Permissions:** mirror `ASN Stock Cap Settings` — System Manager and Stock Manager write; Stock User read.
- **Quantities** are in the item's stock UOM, consistent with every other figure the rule compares.

### Unchanged: `ASN Stock Cap Settings`

Keeps its existing job: for a branch, which warehouses' stock counts toward the cap. The two doctypes are orthogonal — settings say *what to count*, cap rows say *how much is allowed*. Both are required for enforcement.

### Removed: `Item.custom_max_stock`

The custom field, its `custom_fields/item.py` definition, its `after_install` call, and the `create_item_max_stock_field` patch are all removed. A new patch deletes the `Item-custom_max_stock` Custom Field from existing sites.

**This discards existing values.** That is deliberate: a field that remains visible on the Item form while no longer affecting anything is precisely the failure this project already hit once, where a configured ceiling silently did nothing and gave no signal why. Deleting it makes the retirement legible.

## Evaluation

The pure layer changes in exactly one way — the key of the cap lookup:

```python
# asn_module/stock_cap/models.py
max_stock: dict[str, float]              # was, keyed by item_code
max_stock: dict[tuple[str, str], float]  # now, keyed by (branch, item_code)
```

`evaluate()` changes only its two lookups, from `.get(item_code)` to `.get((branch, item_code))`. Everything else is untouched and must stay that way:

- comparison is **strictly greater**; `projected == cap` is allowed
- `cap <= 0` skips the line — this is what makes `max_qty = 0` and a missing row behave identically
- non-positive `stock_qty` lines are skipped, so a document adding nothing is never refused
- `evaluate()` keeps returning `(breaches, accepted)`
- `on_hand` and `in_transit` keep their `(branch, item_code)` keys — pooling is unaffected

`fetch._fetch_max_stock(item_codes)` becomes `_fetch_max_stock(branches, item_codes)`, reading the new doctype for the `(branch, item)` pairs in play. It is guarded by `frappe.db.table_exists("ASN Item Branch Cap")` and returns `{}` when absent, preserving the fail-open rule for a site that has not migrated.

`Breach` gains nothing. It already carries `branch`, so messages and the redaction gate need no change.

## Configuration warning

`ASN Item Branch Cap.validate()`:

1. Rejects a negative `max_qty`.
2. Rejects a `branch` or `item` containing `::`, which would break the composite name's uniqueness.
3. Warns, without blocking, when the row's branch has no enabled `ASN Stock Cap Settings` with at least one warehouse:

   > Branch {0} has no enabled ASN Stock Cap Settings, so this limit will not be enforced until its cap warehouses are configured.

Non-blocking is deliberate. It preserves the fail-open constraint, and it lets an administrator set ceilings before wiring warehouses. The warning fires at the moment of configuration, where someone can act on it — not at ASN submit time, where it would be noise to a supplier who cannot fix it.

## Constraints inherited

All Global Constraints from the original design continue to bind:

- tab indentation, double quotes, 110 char lines
- must run on Frappe/ERPNext v15 and v16
- user-visible strings wrapped in `_()`
- test naming `test_<what>_<expected_outcome>`
- fail open on absent configuration; never fail open on a permission check
- quantities always in stock UOM
- advisory, not transactional — no locking, no `FOR UPDATE`
- never disclose On Hand, In Transit, or Maximum Stock to users without `read` on `Item`

## Testing

**New** — `ASN Item Branch Cap`: composite naming prevents duplicates; negative `max_qty` rejected; warning fires for an unconfigured branch and stays silent for a configured one.

**Changed** — evaluate and property tests re-keyed to `(branch, item)`; a case proving two branches with different ceilings for the same item are judged independently; fetch tests for the new query and its `table_exists` fail-open; every test and the Cypress seeder that currently writes `custom_max_stock`.

**Removed** — tests asserting the `Item.custom_max_stock` custom field is created.

The Cypress `seed_stock_cap_context` helper switches to creating an `ASN Item Branch Cap` row instead of setting the item field.

## Delivery

Built on a branch off `main` **after PR #26 merges**. Folding a data-model change into #26 would invalidate a completed review of 31 commits.

Deploying needs `bench migrate` (creates the doctype, runs the removal patch) followed by `bench --site <site> clear-cache`. Until an `ASN Item Branch Cap` row exists for a branch, that branch is uncapped — expected, and the reason for the save-time warning.

## Open risk

Retiring `Item.custom_max_stock` means any site relying on it loses enforcement the moment this ships, until branch rows are created. That is the accepted cost of a single source of truth; it was chosen over a migration that would have had to guess which branches each item's global value applied to.
