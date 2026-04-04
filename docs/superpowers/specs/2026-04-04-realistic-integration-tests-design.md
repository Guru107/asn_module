# Realistic integration tests — design

**Status:** Approved (brainstorming session, 2026-04-04)  
**Policy:** **A** — Minimize mocks; maximize fidelity to production behavior; accept slower CI unless a follow-up split is needed.

---

## 1. Goals

- Strengthen automated tests so they **exercise real Frappe/ERPNext behavior** with **minimal patching** (`get_roles`, attachment mocks, fake handlers on golden paths).
- Cover **integration surfaces**: ASN lifecycle, **scan codes + registry + dispatch**, **registered QR handlers**, **ASN Transition Log** / summary / report alignment, and **registry integrity** (`verify_scan_code_registry`).
- Prefer **fewer, deeper** tests over many shallow duplicates.

---

## 2. Non-goals

- Replacing every existing **unit** test that uses `fake_handler` or narrow mocks (those remain valuable for speed and isolation).
- Expanding Cypress into full API-backed E2E in this spec (optional later work).
- Changing production business logic solely to make tests easier (tests adapt to product rules).

---

## 3. Scope map (“all functionality” for this effort)

| Domain | Integration focus |
|--------|-------------------|
| **ASN** | Submit/cancel (or equivalent) with **real attachment** rules; multi-item ASNs where handlers differ. |
| **Scan codes + registry** | `get_or_create_scan_code`; registry rows; dispatch with **real** `handler_method` targets. |
| **Handlers** | Each **production-registered** action: build minimal real doc state → `dispatch(code=…)` → assert created/linked ERPNext docs. |
| **Traceability** | Rows in **ASN Transition Log** after transitions; consistency with **`get_item_transition_summary`** and **ASN Item Transition Trace** report. |
| **Integrity** | `verify_scan_code_registry` happy path + controlled orphan scenario with safe teardown. |
| **Hooks / notifications** | Only where they change **observable** persisted state or outbound records worth locking in. |

---

## 4. Auth and permissions

- **Golden paths:** Use **real Users** (or ERPNext test users if appropriate) with roles matching **production scanner/operator** needs; **`frappe.set_user`** in tests with restore in `tearDown` / class cleanup.
- **Negative paths:** Optional small module may still **`patch`** `get_roles` **only** for explicit “wrong role” regressions, documented as exceptions to policy **A**.

---

## 5. Attachments

- On golden paths that today use **`_mock_asn_attachments`**, move to a **minimal real file** attachment via supported Frappe APIs (temp file + attach), so **submit** matches production validation.
- Document in implementation plan the **minimum files** required per ASN state if rules are configurable.

---

## 6. Dispatch and handlers

- For each **`action_key`** registered for real use:
  - Establish **minimum prerequisite** documents (submitted ASN, etc.).
  - Obtain scan code via **`get_or_create_scan_code`** (or documented alternative).
  - Call **`dispatch(code=…, device_info=…)`** under the **real test user**.
  - Assert **doc fields, docstatus, links**, and **no duplicate side effects** where idempotency is required.

---

## 7. Traceability and reporting

- After **ASN → PR → (PI when in scope)** (and other major handler outcomes), assert **ASN Transition Log** content (state, status, refs, actor where stable).
- Add cross-checks: **`get_item_transition_summary(asn)`** vs underlying log rows; **report `execute`** vs same rows within defined filters/limits.

---

## 8. Registry integrity

- **Happy path:** After normal flow, `verify_scan_code_registry` returns **`ok: true`** (or equivalent).
- **Sad path:** Introduce a **deliberate orphan** Scan Code (or unlink target) in a **tearDown-safe** way; expect **`ok: false`** and listed orphans; always restore DB state.

---

## 9. Performance and CI

- Default expectation: **`bench run-tests --app asn_module`** includes new integration coverage; **runtime will increase**.
- **Optional follow-up (YAGNI until measured):** separate module e.g. `asn_module.tests.integration_realistic` run on **schedule** or **manual** workflow if PR jobs exceed acceptable duration. If added, document how to run locally and prevent bitrot.

---

## 10. Success criteria

- Main golden-path flows run **without** patching **`frappe.get_roles`** (except documented negative tests).
- At least **one** integration test per **production** dispatch action registered for the app.
- Transition log **and** summary/report **consistency** asserted on at least one full journey (ASN → PR → PI as applicable).
- `verify_scan_code_registry` covered for **ok** and **not ok** with cleanup guarantees.

---

## 11. Next steps

1. User reviews this committed spec on disk.
2. After approval, **`writing-plans`** produces `docs/superpowers/plans/YYYY-MM-DD-realistic-integration-tests.md` with file-level tasks, fixtures, and verification commands.
3. Implement task-by-task (TDD where practical).
