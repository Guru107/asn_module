# Cypress API-backed E2E — design

**Status:** Approved (brainstorming session, 2026-04-04)  
**Related:** [Realistic integration tests (Python)](2026-04-04-realistic-integration-tests-design.md) — complementary; that spec remains the primary home for deep `bench run-tests` coverage. This spec adds **browser E2E** with **API seeding**.

---

## 1. Goals

- Extend Cypress beyond **smoke** with **two shallow, end-to-end** specs:
  1. **ASN desk** — seed minimal real data via `cy.call` / `cy.request`, open ASN list/detail in the desk, assert stable UI signals.
  2. **Scan station** — seed a **dispatchable** scan context (minimal real documents + scan code resolution via server), visit Scan Station, drive the input, assert success UI or an expected error path.
- Use **pattern A** everywhere: **API seed first**, **UI assert second** (`cy.visit` + DOM).

---

## 2. Non-goals

- Replacing or duplicating the full matrix of Python integration tests (dispatch actions, trace/report alignment, `verify_scan_code_registry`, etc.).
- Covering every registered handler in Cypress in the first wave.
- Migrating to Playwright.
- Running the new specs on **every pull request** (see §5).

---

## 3. Suite layout and configuration

- **Folder-based split (recommended implementation):**
  - `cypress/integration/smoke/` — PR-safe specs (existing smoke tests live here after move).
  - `cypress/integration/nightly/` — new API-backed specs.
- **`cypress.config.cjs`** selects `specPattern` from an environment variable, e.g. `E2E_SUITE`:
  - `smoke` — only `cypress/integration/smoke/**/*.js` (exact glob is an implementation detail).
  - `nightly` — only `cypress/integration/nightly/**/*.js`.
  - `all` — optional; both globs (for a full pass when desired).
- **`scripts/run_ephemeral_e2e.sh`** passes `E2E_SUITE` through to the process that runs Cypress (exact wiring is an implementation detail; must work locally and in CI).

---

## 4. CI / workflow policy

- **`pull_request`:** run **`E2E_SUITE=smoke`** only — keeps PR jobs duration stable.
- **`schedule` and `workflow_dispatch`:** run **`E2E_SUITE=nightly`** — new API-backed specs.
- **Default for scheduled runs:** nightly-only **extra** specs (smoke not required on the same job unless product asks to add `all` later).
- **Matrix:** retain **Frappe 15 + 16** (and matching ERPNext) as today; nightly must pass on both.

---

## 5. Data, auth, and stability

- **Seeding:** Prefer **`cy.call`** to whitelisted Frappe methods; document any new `allow_tests` / server helpers if unavoidable.
- **Heavy setup (especially scan station):** Building a **dispatchable** context (e.g. submitted ASN → PR → registry → scan code) can require many chained calls from Cypress. If that exceeds a **small, readable** number of steps (implementation plan should pick a concrete threshold, e.g. **more than ~3–4** `cy.call` hops), add **one** small **server-side test helper** (whitelisted for `allow_tests` / UI tests), callable via a **single** `cy.call`, that returns whatever the spec needs (e.g. scan code string + doc names). Reuse existing Python integration builders where possible instead of duplicating business logic in JS.
- **User:** Seeding as **Administrator** is acceptable; document if a spec must assert under a **non-admin** desk user (then add role setup via API in that spec).
- **Names:** Use **unique** document names per run (timestamp/hash) to avoid ambiguity in logs even though ephemeral sites isolate DBs.
- **SPA / desk:** Reuse smoke learnings — avoid **double `cy.visit`** to the same desk route in one spec when Frappe does not re-run page boot; prefer **one visit** per spec or explicit reload/cache-bust if a second entry is ever required.
- **Config:** Keep **`adminPassword`** and **`routePrefix`** aligned with `run_ephemeral_e2e.sh` / workflow env (see existing E2E workflow design).

---

## 6. Success criteria

- Nightly workflow **green** on both matrix rows.
- PR workflow **duration** unchanged in intent (smoke-only).
- Written spec-level notes (in implementation plan) for: seeded entities per test, APIs called, and UI assertions.

---

## 7. Next steps

1. User reviews this committed spec on disk.
2. After approval, use **`writing-plans`** to add a dated implementation plan (config + workflow + script + spec moves + two nightly specs + verification).
3. Implement task-by-task.
