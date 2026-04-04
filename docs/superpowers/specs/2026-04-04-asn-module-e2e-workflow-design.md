# ASN module — dedicated E2E workflow (Cypress + bench)

**Status:** Approved (brainstorming session, 2026-04-04)  
**References:** [production-entry-app `e2e.yml`](https://github.com/Guru107/production-entry-app/blob/develop/.github/workflows/e2e.yml), [`run_ephemeral_e2e.sh`](https://github.com/Guru107/production-entry-app/blob/develop/scripts/run_ephemeral_e2e.sh)

---

## 1. Goals

- Add a **separate GitHub Actions workflow** for **browser E2E** tests, structurally aligned with `production-entry-app`.
- Keep **Cypress** and **`bench run-ui-tests asn_module`** (no Playwright in this iteration).
- **Remove** Cypress from the main **`ci.yml`** / **`run_ephemeral_python_tests.sh`** so Python CI stays fast and UI coverage lives in one place.
- Run E2E on a **matrix: Frappe 15 + ERPNext 15** and **Frappe 16 + ERPNext 16**, with Python/Node versions matching the reference pattern.

---

## 2. Non-goals

- Migrating specs to Playwright.
- Changing ASN business logic or scan/trace features (only CI/script/test-routing changes).

---

## 3. Workflow: `.github/workflows/e2e.yml`

### 3.1 Triggers

- **`pull_request`**, with **`paths-ignore`**: `**/*.md`, `docs/**` (adjust later if needed).
- **`workflow_dispatch`**.
- **`schedule`**: nightly cron (e.g. `0 2 * * *` UTC to mirror reference; exact value is implementation detail).

### 3.2 Concurrency

- Define a concurrency group (e.g. keyed by workflow + PR number or branch) with **`cancel-in-progress: true`** where appropriate, consistent with existing `ci.yml` patterns.

### 3.3 Job matrix

| Dimension | Frappe 15 row | Frappe 16 row |
|-----------|----------------|---------------|
| Frappe / ERPNext branch | `version-15` | `version-16` |
| Python | `3.10` | `3.14` |
| Node | `20` | `24` |
| Route prefix for Cypress | `app` | `desk` |

Expose matrix values via job **`env`** (e.g. `FRAPPE_VERSION`, `ERPNEXT_VERSION`, `FRAPPE_ROUTE_PREFIX` or `CYPRESS_FRAPPE_ROUTE_PREFIX`).

### 3.4 Services

- **redis-cache** and **redis-queue** on ports **13000** and **11000** (match current `ci.yml`).
- **MariaDB:** use a **single** image version for **both** matrix rows initially (**`mariadb:11.8`**, same as current `ci.yml`). If Frappe 15 proves incompatible, document switching to **`mariadb:10.6`** for the v15 row only in a follow-up.

### 3.5 Steps (high level)

1. Checkout, setup Python (matrix), setup Node (matrix), MariaDB client.
2. `pip install frappe-bench`; `bench init` with `--frappe-branch version-$FRAPPE_VERSION` (and same skip flags as `ci.yml` where applicable).
3. Global MariaDB charset/collation statements (same as `ci.yml`).
4. `bench get-app` **asn_module** from `$GITHUB_WORKSPACE`; `bench get-app --branch version-$ERPNEXT_VERSION` **erpnext**; `bench setup requirements --dev`; **`bench build`** (full, not only `--app asn_module`).
5. No separate `npm install` for Cypress unless required later — **`bench run-ui-tests`** uses Frappe’s Cypress toolchain from the bench environment.
6. Run **`chmod +x scripts/run_ephemeral_e2e.sh`** and invoke with **`BENCH_ROOT`**, **`DB_ROOT_PASSWORD`**, and mode:
   - **PR / `workflow_dispatch`:** `smoke` (default).
   - **`schedule`:** `ci` (may run the same command as `smoke` until more specs exist; structure must allow diverging later).

### 3.6 Artifacts (`if: always()`)

- **Cypress:** `cypress/videos`, `cypress/screenshots` (paths under workspace).
- **Serve log:** e.g. `/tmp/bench-serve-<run-id>.log` or fixed path; names must **include matrix variant** (e.g. `cypress-artifacts-v15`, `bench-serve-v16`).

---

## 4. Script: `scripts/run_ephemeral_e2e.sh`

New script, behaviorally analogous to **`production-entry-app`**’s `run_ephemeral_e2e.sh`, adapted for **asn_module** and **Cypress**.

### 4.1 Responsibilities

- **`set -euo pipefail`**; **`trap`** cleanup: kill serve process, **`bench drop-site`** ephemeral site, restore previous `currentsite.txt` if present (mirror reference).
- Ephemeral **`SITE_NAME`** (e.g. `asn-e2e-<sanitized-run-id>`).
- **`bench new-site`**, install **erpnext**, install **asn_module**, then **`bench build --app asn_module`** (same pattern as `run_ephemeral_python_tests.sh`). The workflow step runs a **full `bench build`** once after `get-app` / `setup requirements` so the bench tree is compiled before the script runs; the script’s app build covers the ephemeral site install path.
- **Fixtures:** `erpnext.setup.setup_wizard.operations.install_fixtures.install` with `["India"]`, with the **same tolerant handling** as `run_ephemeral_python_tests.sh` for known **`NestedSetRecursionError`** / item-tree messages.
- **`bench --site $SITE set-config allow_tests true`**; **`asn_module.utils.test_setup.before_tests`**.
- Optional flags aligned with reference where useful: **`developer_mode`**, **`allow_e2e_tests`** (only if the site exposes such config and tests expect it; otherwise omit to avoid unused knobs).
- **`bench use $SITE_NAME`** before serve.
- **Serve:** `bench --site "$SITE_NAME" serve --port <PORT> --noreload` with **`PORT`** fixed when **`CI=true`** (e.g. **18002**, like reference). Log to **`/tmp/bench-serve-...log`**.
- **Readiness:** HTTP check on **`/login`** (reference) or equivalent stable endpoint; fail fast with log dump on timeout.
- **Hostname / hosts:** append **`127.0.0.1 $SITE_NAME`** to **`/etc/hosts`** (requires `sudo`, as today) so **`frappe.utils.get_site_url`** and **`bench run-ui-tests`** **`CYPRESS_baseUrl`** match.
- **Test invocation:**  
  `bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron`  
  (Electron avoids extra browser installs in CI.)

### 4.2 Modes (positional argument)

- **`smoke`** — default PR path.
- **`ci`** — scheduled / fuller run; initially may equal `smoke`; reserved for future expansion.

Pass-through for ad-hoc Cypress args is optional (YAGNI unless needed).

### 4.3 Environment variables

- **`BENCH_ROOT`**, **`DB_ROOT_USERNAME`**, **`DB_ROOT_PASSWORD`**, **`EPHEMERAL_ADMIN_PASSWORD`** (default e.g. `admin` or align with Python script).
- **`FRAPPE_ROUTE_PREFIX`** / **`CYPRESS_FRAPPE_ROUTE_PREFIX`** — consumed by Cypress config/specs for v15 vs v16 routes.

---

## 5. Cypress routing (v15 vs v16)

- **`cypress.config.cjs`:** define `env.routePrefix` from `process.env.FRAPPE_ROUTE_PREFIX` or `CYPRESS_FRAPPE_ROUTE_PREFIX`, default **`app`** for local dev.
- **Integration specs:** replace hard-coded **`/app/...`** with **`/${Cypress.env('routePrefix')}/...`** (or helper) for **scan station** and **ASN list** visits.
- Ensure **`cy.login()`** and Frappe’s support file remain compatible with both versions (Frappe’s `cypress/support` from sibling app).

---

## 6. Changes to existing CI

### 6.1 `.github/workflows/ci.yml`

- Remove **`RUN_UI_TESTS: "1"`** from the Server job env.
- Remove the **“Upload Cypress artifacts on failure”** step (or replace with a one-line comment pointing to **`e2e.yml`**).

### 6.2 `scripts/run_ephemeral_python_tests.sh`

- Delete the entire **`RUN_UI_TESTS`** block (hosts, serve, wait, **`run-ui-tests`**).
- Keep Python test execution and ephemeral site lifecycle unchanged otherwise.

---

## 7. Risks and policy

- **Frappe 15 support:** `pyproject.toml` does not formally declare Frappe 15; the **v15 matrix row is an explicit product decision**. Both rows are **required checks** once the workflow is merged; if v15 is red, fix forward or temporarily disable the row (out of scope for this spec unless agreed).
- **MariaDB:** single **11.8** for both rows may expose Frappe 15 edge cases; split images only if CI proves it necessary.
- **CI duration:** Full **`bench build`** + matrix doubles E2E wall time vs a single row; acceptable per stakeholder choice **B**.

---

## 8. Acceptance criteria

- **`ci.yml`** completes **without** running Cypress; Python tests unchanged in behavior.
- **`e2e.yml`** runs on PR (with path filters), manual dispatch, and schedule.
- Both matrix jobs run **smoke** Cypress successfully when the app supports both Frappe versions.
- On failure, artifacts (**videos**, **screenshots**, **serve log**) are uploaded with matrix-specific names.

---

## 9. Next step

After this spec is reviewed in-repo, create an implementation plan under **`docs/superpowers/plans/`** ( **`writing-plans`** skill ) and implement task-by-task.
