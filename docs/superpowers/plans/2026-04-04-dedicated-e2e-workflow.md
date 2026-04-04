# Dedicated E2E workflow (Cypress + bench) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `.github/workflows/e2e.yml` and `scripts/run_ephemeral_e2e.sh`, parameterize Cypress routes for Frappe 15/16, and remove Cypress from `ci.yml` / `run_ephemeral_python_tests.sh`.

**Architecture:** GitHub Actions matrix runs two jobs (Frappe/ERPNext 15 and 16) that bootstrap a bench, run a self-contained bash script creating an ephemeral site, serving with `bench serve --noreload`, then `bench run-ui-tests asn_module --headless --browser electron`. Python CI stays in `ci.yml` only.

**Tech Stack:** GitHub Actions, `frappe-bench`, MariaDB 11.8, Redis (13000/11000), Cypress via Frappe’s `yarn` bin, bash.

**Spec:** `docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md`

---

## File map

| File | Role |
|------|------|
| `.github/workflows/e2e.yml` | **Create** — triggers, matrix, services, bench bootstrap, invoke script, artifacts |
| `scripts/run_ephemeral_e2e.sh` | **Create** — ephemeral site, fixtures (tolerant), serve, hosts, Cypress |
| `scripts/run_ephemeral_python_tests.sh` | **Modify** — delete `RUN_UI_TESTS` block |
| `.github/workflows/ci.yml` | **Modify** — remove `RUN_UI_TESTS`, Cypress artifact step; optional comment to `e2e.yml` |
| `cypress.config.cjs` | **Modify** — `env.routePrefix` from `process.env` |
| `cypress/integration/*.js` | **Modify** — use `routePrefix` in `cy.visit` paths |

---

### Task 1: Remove Cypress from Python CI path

**Files:**
- Modify: `scripts/run_ephemeral_python_tests.sh`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Delete the `RUN_UI_TESTS` block** in `run_ephemeral_python_tests.sh` (lines from the `if [ "${RUN_UI_TESTS:-}" = "1" ]` through the final `fi` for that block, including `SERVE_PID` handling that exists only for UI tests).

- [ ] **Step 2: Simplify `cleanup()`** in the same script: remove `SERVE_PID` kill/wait if it is no longer set anywhere in the file.

- [ ] **Step 3: Edit `ci.yml` Server job**
  - Remove `RUN_UI_TESTS: "1"` from the `Run Tests` step `env`.
  - Remove the step `Upload Cypress artifacts on failure` **or** replace with a YAML comment: `# Browser E2E: see .github/workflows/e2e.yml`.

- [ ] **Step 4: Local sanity** — run `bash -n scripts/run_ephemeral_python_tests.sh` (expect exit 0).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_ephemeral_python_tests.sh .github/workflows/ci.yml
git commit -m "ci: drop Cypress from Python ephemeral script and main workflow"
```

---

### Task 2: Parameterize Cypress route prefix

**Files:**
- Modify: `cypress.config.cjs`
- Modify: `cypress/integration/scan_station_smoke.js`
- Modify: `cypress/integration/asn_desk_smoke.js`

- [ ] **Step 1: Extend `cypress.config.cjs`** so `e2e.env.routePrefix` is:

```javascript
process.env.FRAPPE_ROUTE_PREFIX ||
	process.env.CYPRESS_FRAPPE_ROUTE_PREFIX ||
	"app";
```

- [ ] **Step 2: Add a tiny helper at top of each integration file** (or inline):

```javascript
const route = (path) => `/${Cypress.env("routePrefix")}${path}`;
```

Use it so visits become e.g. `cy.visit(route("/scan-station"))` and `cy.visit(route("/asn"))` (leading slash only once — adjust helper if paths already include `/`).

- [ ] **Step 3: Run Prettier** on touched JS (repo uses pre-commit Prettier v2.7.1):

```bash
cd /path/to/asn_module
pre-commit run prettier --files cypress.config.cjs cypress/integration/*.js
```

- [ ] **Step 4: Commit**

```bash
git add cypress.config.cjs cypress/integration/*.js
git commit -m "test(cypress): route prefix from env for Frappe 15/16 matrix"
```

---

### Task 3: Add `scripts/run_ephemeral_e2e.sh`

**Files:**
- Create: `scripts/run_ephemeral_e2e.sh`

Reference behavior: `production-entry-app` `run_ephemeral_e2e.sh` + existing `run_ephemeral_python_tests.sh` (fixtures tolerance).

- [ ] **Step 1: Shebang and strict mode** — `#!/usr/bin/env bash`, `set -euo pipefail`.

- [ ] **Step 2: Variables** — `APP_ROOT`, `BENCH_ROOT` (default align with python script: sibling `bench16` or require `BENCH_ROOT` in CI), `DB_ROOT_*`, `EPHEMERAL_ADMIN_PASSWORD` (default `admin`), `RUN_ID`, `SITE_NAME="asn-e2e-${RUN_ID//[^a-zA-Z0-9]/}"`, `E2E_MODE="${1:-smoke}"`, `SERVE_PORT` default empty; if `CI=true` and empty, `SERVE_PORT=18002`. `SERVE_LOG="/tmp/bench-serve-${RUN_ID}.log"`, `SERVER_PID=""`, `PREVIOUS_SITE=""`.

- [ ] **Step 3: `cleanup` trap** — kill `$SERVER_PID`; `bench drop-site "$SITE_NAME"` if site dir exists; if `PREVIOUS_SITE` was saved from `currentsite.txt`, `bench use "$PREVIOUS_SITE"` best-effort; preserve exit code.

- [ ] **Step 4: Require `DB_ROOT_PASSWORD`**.

- [ ] **Step 5: Save and `bench use`** — if `sites/currentsite.txt` exists, read into `PREVIOUS_SITE`.

- [ ] **Step 6: Site lifecycle** (under `BENCH_ROOT`): `bench new-site`, `install-app erpnext`, `install-app asn_module`, `bench build --app asn_module`.

- [ ] **Step 7: Fixtures** — same pattern as `run_ephemeral_python_tests.sh`: `set +e`, capture output of `bench execute erpnext...install_fixtures... India`, `set -e`, grep for `NestedSetRecursionError|Item cannot be added to its own descendants` to allow continue, else fail.

- [ ] **Step 8: Test bootstrap** — `bench --site "$SITE_NAME" set-config allow_tests true`, `bench execute asn_module.utils.test_setup.before_tests`.

- [ ] **Step 9: `bench use "$SITE_NAME"`**.

- [ ] **Step 10: `/etc/hosts`** — `echo "127.0.0.1 $SITE_NAME" | sudo tee -a /etc/hosts >/dev/null`.

- [ ] **Step 11: Serve** — `bench --site "$SITE_NAME" serve --port "$SERVE_PORT" --noreload >"$SERVE_LOG" 2>&1 &`, `SERVER_PID=$!`.

- [ ] **Step 12: Wait for readiness** — loop ~45×2s: check process alive; `curl -sSf "http://${SITE_NAME}:${SERVE_PORT}/api/method/frappe.ping"` **or** `http://${SITE_NAME}:${SERVE_PORT}/login` per spec (pick one and document in script comment); on failure print log and exit 1.

- [ ] **Step 13: Export route prefix for Cypress** — `export FRAPPE_ROUTE_PREFIX="${FRAPPE_ROUTE_PREFIX:-app}"` (workflow will set per matrix).

- [ ] **Step 14: Run Cypress** — `case "$E2E_MODE" in smoke|ci) bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron ;; *) echo "Unknown mode"; exit 1 ;; esac`. Initially `smoke` and `ci` use the **same** command.

- [ ] **Step 15: `chmod +x`** and `bash -n scripts/run_ephemeral_e2e.sh`.

- [ ] **Step 16: Commit**

```bash
git add scripts/run_ephemeral_e2e.sh
git commit -m "feat: ephemeral bench script for Cypress e2e (smoke/ci modes)"
```

**Note:** If `get_site_url` uses a port different from `SERVE_PORT`, align serve port with what Frappe reports (spec requires hostname + `bench run-ui-tests` baseUrl). Prefer fixed `SERVE_PORT` in CI and ensure site config / URL resolution matches (same pattern as prior hosts + `SITE_NAME` approach).

---

### Task 4: Add `.github/workflows/e2e.yml`

**Files:**
- Create: `.github/workflows/e2e.yml`

- [ ] **Step 1: `name`, `on`** — `pull_request` + `paths-ignore` (`**/*.md`, `docs/**`), `workflow_dispatch`, `schedule` cron `0 2 * * *`.

- [ ] **Step 2: `concurrency`** — e.g. `group: e2e-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref_name }}-${{ matrix.frappe_version }}-${{ matrix.erpnext_version }}`, `cancel-in-progress: true`. Define matrix keys `frappe_version`, `erpnext_version`, `python_version`, `node_version`, `frappe_route_prefix` in `matrix.include` matching spec (15/app, 16/desk).

- [ ] **Step 3: Job `env`** — `FRAPPE_VERSION: ${{ matrix.frappe_version }}`, `ERPNEXT_VERSION: ${{ matrix.erpnext_version }}`, `FRAPPE_ROUTE_PREFIX: ${{ matrix.frappe_route_prefix }}`, `CI: 'Yes'`.

- [ ] **Step 4: `services`** — copy redis + mariadb blocks from `ci.yml` (ports 13000, 11000, 3306, `mariadb:11.8`).

- [ ] **Step 5: Steps** — checkout v6, setup-python v6 with `${{ matrix.python_version }}`, setup-node v6 with `${{ matrix.node_version }}`, optional pip/yarn caches mirroring `ci.yml` if desired, MariaDB client install, then bench init / charset / `cd ~/frappe-bench` get-app erpnext with `--branch version-$ERPNEXT_VERSION`, get-app asn_module from `$GITHUB_WORKSPACE`, `bench setup requirements --dev`, `bench build`.

- [ ] **Step 6: Run e2e script** from `$GITHUB_WORKSPACE`:

```yaml
- name: Run Cypress E2E
  working-directory: ${{ github.workspace }}
  env:
    DB_ROOT_PASSWORD: root
    BENCH_ROOT: /home/runner/frappe-bench
    FRAPPE_ROUTE_PREFIX: ${{ matrix.frappe_route_prefix }}
  run: |
    chmod +x scripts/run_ephemeral_e2e.sh
    scripts/run_ephemeral_e2e.sh ${{ github.event_name == 'schedule' && 'ci' || 'smoke' }}
```

Adjust expression if `workflow_dispatch` should default to `smoke` (spec: PR and dispatch → `smoke`, schedule → `ci`).

- [ ] **Step 7: Artifacts `if: always()`** — upload `cypress/videos`, `cypress/screenshots` with name `cypress-artifacts-frappe${{ matrix.frappe_version }}`; upload serve log with name `bench-serve-frappe${{ matrix.frappe_version }}` (`if-no-files-found: ignore` where appropriate).

- [ ] **Step 8: `job.name`** — include Frappe version so branch protection is readable, e.g. `E2E (Frappe ${{ matrix.frappe_version }})`.

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/e2e.yml
git commit -m "ci: add matrixed e2e workflow for Cypress (Frappe 15/16)"
```

---

### Task 5: Verification and ops handoff

- [ ] **Step 1: Push branch** and open or update PR; wait for **`ci.yml`** and **`e2e.yml`** runs.

- [ ] **Step 2: Confirm** `ci.yml` has **no** Cypress step; **`e2e.yml`** both matrix legs complete (or document if Frappe 15 row needs follow-up).

- [ ] **Step 3: If v16 `desk` prefix breaks visits**, try `frappe_route_prefix: app` for the 16 row temporarily and note in commit/spec follow-up (spec allows validation).

- [ ] **Step 4: Electron failure** — if Electron fails on runner, add Chrome install step to workflow and change script to `CYPRESS_BROWSER=chrome` or pass `--browser chrome` (escape hatch in spec).

- [ ] **Step 5: Branch protection** — in GitHub repo settings, add required status checks matching the **exact** job names from the workflow after first green run.

- [ ] **Step 6: Final commit** only if any fix from Step 3–4 was needed.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-04-dedicated-e2e-workflow.md`.

**1. Subagent-driven (recommended)** — fresh subagent per task, review between tasks (@superpowers:subagent-driven-development).

**2. Inline execution** — run tasks in this session with checkpoints (@superpowers:executing-plans).

Which approach do you want?
