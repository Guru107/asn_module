# Audit Remediation — Design

**Status:** proposed
**Date:** 2026-11-01
**References:** [#57](https://github.com/Guru107/asn_module/issues/57) (module internals), [#58](https://github.com/Guru107/asn_module/issues/58) (cypress, property tests, portal templates, docs)
**Verified:** every finding below was re-checked against `main` (`2341daa`) on 2026-11-01; all 18 confirmed, none already fixed.

## Problem

Two read-only audits found 18 defects: four corrupt data or lose it silently (wrong quantities credited between ASN lines, putaway bypassing Quality Inspection, half-finished documents committed on scan failure, portal drafts dropping rows), one is a double-scan race, two are security holes, several are performance and CI-coverage gaps, and the rest are deletable duplication.

## Decision summary

| Question | Decision |
| --- | --- |
| Scope | All 18 findings, in six phases ordered by risk |
| Backward compatibility | Out of scope (pre-production, per AGENTS.md) — the `idx`-keyed mapping JSON is rewritten, not migrated |
| How is the scan code claimed? | Atomically, before the handler runs — but only for single-use actions; ASN scans keep reopening their own drafts |
| Test rule | Every behavioural fix ships with a regression test that fails without it |

**Explicitly not doing:** migrating existing draft receipts' `idx`-keyed mapping JSON; a per-item inspection filter inside `confirm_putaway` (unneeded once mixed receipts stop receiving the QR); per-warehouse stock cap changes (unrelated).

## Phase 1 — Data integrity (must fix)

### 1.1 PR↔ASN mapping keyed by row position (#57-1)

`handlers/purchase_receipt.py:863-865` writes `asn_items_map[str(pr_item.idx)]`; readers at `purchase_receipt.py:188-192`, `handlers/purchase_invoice.py:52-54`, `handlers/putaway.py:30-32` do `mapping.get(str(pr_item.idx))`. The desk renumbers rows when a draft is edited, so deleting row 1 re-credits every row's quantity to the wrong ASN line.

**Fix:** key the map by `pr_item.name` (stable across edits). Write it right after `pr.insert()`; the three readers use `mapping.get(pr_item.name)`.

**Test:** scan-create a 3-line draft, delete the first row via the desk, submit, assert each remaining ASN line's Received Qty reflects its own quantity.

### 1.2 Putaway QR on mixed-inspection receipts (#57-2)

`handlers/purchase_receipt.py:994` — `putaway_required = any(...)` attaches the confirm-putaway code when at least one item skips inspection, so an inspection-required item can be put away with no Quality Inspection.

**Fix:** `any(` → `all(`. One word. `confirm_putaway` needs no change: mixed receipts no longer receive the code.

**Test:** receipt with one inspection-free and one inspection-required item asserts no `confirm_putaway` scan code is attached.

### 1.3 Failed scan commits half-finished work (#57-3)

`qr_engine/dispatch.py:285-297` — on handler error, `_log_scan` + `frappe.db.commit()` run before re-raise, persisting whatever the handler already wrote.

**Fix:** take `frappe.db.savepoint()` at the top of `dispatch` (pattern at `asn_new_services.py:883`); in `except`, `rollback_to_savepoint` first, then write the failure log and commit.

**Test:** monkeypatch a handler to raise mid-insert; assert no partial child rows survive and the Failure Scan Log does.

### 1.4 Portal drafts drop rows the picker no longer lists (#58-1)

`templates/pages/asn_new.html:1574-1576` — the draft-restore loop skips any row whose PO line the live picker no longer returns (Remaining Qty 0), and Save rebuilds from rendered rows only, deleting the line without a word.

**Fix:** when `poItems.find(...)` misses, build the row entry from the stored draft row (it carries sr_no, item_code, uom, qty, rate). The server already rejects a qty exceeding remaining with a per-row error, so the supplier is told instead of silently losing the line.

**Test:** portal E2E (or unit test of the restore branch): save a draft, consume the line's remaining qty elsewhere, reopen the draft, assert the row still renders.

## Phase 2 — Concurrency

### 2.1 Double scan creating two drafts (#57-4)

`qr_engine/dispatch.py:221-262` marks the code `Used` only after the handler returns, while the handler checks-then-creates a draft — a ~0.5s race window.

**Fix:** claim before running: `UPDATE tabScan Code SET status='Used' WHERE name=%s AND status='Active'`, proceed only if one row changed, revert on handler failure. **Per-action rule:** ASN scans intentionally reopen their own drafts from `Used` codes (see the comment at `dispatch.py:222`) — the claim applies only to single-use actions (gate-pass → receipt chain), not to the ASN action.

**Test:** two concurrent dispatches of the same code; assert exactly one draft exists.

## Phase 3 — Security

### 3.1 Bulk upload reads any file by URL (#57-6)

`doctype/asn/bulk_upload.py:45-53` — `_read_file_content` fetches a File by client-sent `file_url` with no File read check; parse errors echo cell contents back.

**Fix:** `frappe.has_permission("File", "read", doc=file_doc)` or throw, before `get_content()`.

**Test:** user without read permission on a private file gets a permission error, not file contents.

### 3.2 Typed PO text into `innerHTML` (#58-5)

`templates/pages/asn_new.html:995` — `selectedPoChip.innerHTML = ...${selectedPo}...`; when no suggestion matches, `selectedPo` is raw user input. Self-XSS today, a real hole the day a stored string takes the same path.

**Fix:** build the chip (and the row template at `:1009-1042`) with `textContent` / DOM APIs, as the picker list already does.

**Test:** type `x" onfocus=alert(1) autofocus"` into the PO field, press Set PO, assert the chip renders it as text and no handler attribute exists.

## Phase 4 — Performance & housekeeping

### 4.1 Unindexed lookups on every delete (#57-5)

The `"*"` `on_trash` hook (`hooks.py:160-163`) queries Scan Log by `result_doctype/result_name` (`scan_codes.py:274,308`) and Scan Code by `source_doctype/source_name`; both indexes lead with other columns, and nothing prunes Scan Log.

**Fix:** add indexes `(result_doctype, result_name)` to `scan_log.json` and `(source_doctype, source_name)` to `scan_code.json` (synced on migrate); register `"default_log_clearing_doctypes": {"Scan Log": 180}` in `hooks.py`.

### 4.2 Per-invoice `db.exists` loop (#57-7)

`templates/pages/asn_new_services.py:194-217` — up to 500 queries per bulk CSV.

**Fix:** one `supplier_invoice_no IN (...)` query, set comparison in Python, same error output.

### 4.3 Notifications never created on migrate (#57-8)

`setup.py:15` — `after_migrate` re-runs custom fields but not `create_notifications()`; existing installs never get the four templates.

**Fix:** add `create_notifications()` to `after_migrate` (idempotent by name).

### 4.4 Integrity command loads every row as a document (#57-11)

`commands.py:18-25` — `get_all` + `get_doc` per Scan Code.

**Fix:** one SQL query with `NOT EXISTS` against the source tables.

## Phase 5 — Test coverage

### 5.1 CI property suite skips the stock-cap properties (#58-2)

`property_tests/property_suite.py:7-12` omits `TestStockCapProperties`.

**Fix:** add the import and `__all__` entry. Two lines.

### 5.2 "Portal smoke" tests the desk as Administrator (#58-3)

`cypress/integration/smoke/asn_portal_smoke.js:6-16` — `cy.login()` + `/app/asn`.

**Fix:** seed a supplier context (helper exists) and visit `/asn`, asserting a row renders — mirror of `asn_new_portal_smoke.js`.

## Phase 6 — Deletions & hygiene (~-180 lines)

| # | Item | Fix |
| --- | --- | --- |
| 6.1 | #57-9 twin handlers (`purchase_receipt.py:56-63`) | delete `create_from_asn`; point both `ACTIONS` entries at `create_gate_pass_from_asn` |
| 6.2 | #57-10 dead helper (`asn_new.py:599-620`, zero non-test callers) | delete helper + its tests |
| 6.3 | #57-12 Scan Station routes away per scan (`scan_station.js:61`) | show the document link in the alert instead of `set_route` |
| 6.4 | #58-4 portal helpers triplicated (list page + detail ×2) | one shared JS include under `public/js/`; templates keep only their messages |
| 6.5 | #58-6 32 stale plans describe retired machinery | one `README.md` in `docs/superpowers/plans/`: historical records; current design lives in `CONTEXT.md` and `docs/adr/` |

## Sequencing

Phases in order; each phase is independently shippable. Phase 1 first — all four findings silently corrupt or lose the quantities this module exists to guarantee. 6.1–6.2 are pure deletions and can ride any phase.

## Verification

- Per-finding regression tests above; existing 634 tests stay green (`bench --site dev.localhost run-tests --app asn_module --lightmode`).
- Property suite (`scripts/run_ephemeral_property_tests.sh`) green including `TestStockCapProperties`.
- Cypress smoke + nightly suites green; portal smoke now fails if the supplier portal list breaks.
