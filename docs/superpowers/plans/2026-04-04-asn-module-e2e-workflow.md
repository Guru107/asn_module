# ASN module dedicated E2E workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship and maintain the dedicated Cypress + bench E2E pipeline from `docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md`: matrixed `e2e.yml`, `run_ephemeral_e2e.sh`, route-aware Cypress, no UI tests on the main Python CI path.

**Architecture:** Two GitHub Actions matrix jobs bootstrap Frappe bench (15/ERPNext 15 and 16/ERPNext 16), run one bash script that creates an ephemeral site, serves with `bench serve --noreload`, then `bench run-ui-tests asn_module --headless --browser electron`. Failures upload Cypress videos/screenshots and bench serve logs per matrix row.

**Tech Stack:** GitHub Actions, `frappe-bench`, MariaDB 11.8, Redis (cache 13000, queue 11000), Cypress via Frappe’s bench toolchain, bash.

**Spec:** `docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md`

---

## File map (target / current)


| Path                                        | Responsibility                                                                                                                                                                                                                                                     |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.github/workflows/e2e.yml`                 | PR (paths-ignore `**/*.md`, `docs/`**), `workflow_dispatch`, nightly `schedule`; matrix Python/Node + `FRAPPE_ROUTE_PREFIX`; Redis/MariaDB services; bench init/get-app/build; `MODE=smoke` except `schedule` → `ci`; artifact uploads with matrix-specific names. |
| `scripts/run_ephemeral_e2e.sh`              | Strict bash + trap cleanup; ephemeral `asn-e2e-`* site; erpnext + asn_module; tolerant India fixtures; `allow_tests` + `before_tests`; `/etc/hosts`; serve + readiness HTTP check; `run-ui-tests` in `smoke`                                                       |
| `cypress.config.cjs`                        | Resolve Frappe `support/e2e.js` via `BENCH_ROOT` or sibling `frappe/`; `env.routePrefix` and `env.adminPassword` from env.                                                                                                                                         |
| `cypress/integration/scan_station_smoke.js` | Smoke: `route()` helper + scan station + legacy token message.                                                                                                                                                                                                     |
| `cypress/integration/asn_desk_smoke.js`     | Smoke: ASN list visibility.                                                                                                                                                                                                                                        |
| `.github/workflows/ci.yml`                  | Python/server tests only; comment pointing to `e2e.yml` (no `RUN_UI_TESTS`, no Cypress artifacts step).                                                                                                                                                            |
| `scripts/run_ephemeral_python_tests.sh`     | Ephemeral Python tests only (no `run-ui-tests` block).                                                                                                                                                                                                             |


**Implementation note:** The repo already contains the rows above for §3–§6 of the spec. Remaining work is **spec/CI alignment** (serve port under Actions), **documentation hygiene**, and **acceptance verification** / branch protection.

---

### Task 1: Align fixed serve port with spec §4.1 when `CI` is not the string `true`

**Files:**

- Modify: `scripts/run_ephemeral_e2e.sh` (lines 24–29, the `SERVE_PORT` default block)

**Context:** `.github/workflows/e2e.yml` sets job-level `CI: "Yes"` (Frappe convention). The script only forces port `18002` when `[ "${CI:-}" = "true" ]`, so Actions runs can default to port `8000` instead of the spec’s fixed CI port. GitHub sets `GITHUB_ACTIONS=true` on runners; use that as an additional sentinel.

- **Step 1: Capture current condition (baseline)**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
sed -n '24,29p' scripts/run_ephemeral_e2e.sh
```

Expected (approximate):

```text
if [ -z "$SERVE_PORT" ] && [ "${CI:-}" = "true" ]; then
	SERVE_PORT="18002"
fi
if [ -z "$SERVE_PORT" ]; then
	SERVE_PORT="8000"
fi
```

- **Step 2: Replace the first `SERVE_PORT` default block** with:

```bash
if [ -z "$SERVE_PORT" ] && { [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]; }; then
	SERVE_PORT="18002"
fi
if [ -z "$SERVE_PORT" ]; then
	SERVE_PORT="8000"
fi
```

- **Step 3: Syntax-check the script**

Run:

```bash
bash -n "$(git rev-parse --show-toplevel)/scripts/run_ephemeral_e2e.sh"
```

Expected: exit code `0`, no output.

- **Step 4: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add scripts/run_ephemeral_e2e.sh
git commit -m "fix(e2e): use fixed serve port on GitHub Actions (GITHUB_ACTIONS)"
```

---

### Task 2: Verify §6 — Python CI path excludes Cypress

**Files:**

- Read-only: `.github/workflows/ci.yml`
- Read-only: `scripts/run_ephemeral_python_tests.sh`
- **Step 1: Assert no UI-test env or commands in `ci.yml`**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
rg -n "RUN_UI_TESTS|cypress|run-ui-tests" .github/workflows/ci.yml || true
```

Expected: no matches (exit code `1` from `rg` is OK when there are zero matches).

- **Step 2: Assert Python ephemeral script has no Cypress block**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
rg -n "RUN_UI_TESTS|run-ui-tests|cypress" scripts/run_ephemeral_python_tests.sh || true
```

Expected: no matches.

- **Step 3: Confirm pointer comment in `ci.yml`**

Run:

```bash
rg -n "e2e.yml" "$(git rev-parse --show-toplevel)/.github/workflows/ci.yml"
```

Expected: at least one line containing `.github/workflows/e2e.yml`.

- **Step 4: Commit**

No commit if all checks already pass (nothing to change).

---

### Task 3: Verify §3 / §5 — workflow matrix and Cypress routing

**Files:**

- Read-only: `.github/workflows/e2e.yml`
- Read-only: `cypress.config.cjs`
- Read-only: `cypress/integration/scan_station_smoke.js`
- Read-only: `cypress/integration/asn_desk_smoke.js`
- **Step 1: Matrix includes both Frappe rows and passes route prefix**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
rg -n "frappe_version:|frappe_route_prefix:|FRAPPE_ROUTE_PREFIX" .github/workflows/e2e.yml
```

Expected: entries for `15` and `16`, and `FRAPPE_ROUTE_PREFIX` in job `env` and in the `Run Cypress E2E` step.

- **Step 2: MODE is `smoke` for PR and `workflow_dispatch`, `ci` for `schedule`**

Run:

```bash
sed -n '117,130p' "$(git rev-parse --show-toplevel)/.github/workflows/e2e.yml"
```

Expected: `MODE="smoke"` and `if` on `github.event_name` / `schedule` setting `MODE="ci"`.

- **Step 3: Cypress config exposes `routePrefix` and `adminPassword`**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
node -e "const c=require('./cypress.config.cjs'); console.log(c.e2e.env.routePrefix||'MISSING', c.e2e.env.adminPassword||'MISSING')"
```

Expected: prints `app admin` (defaults when env vars unset).

- **Step 4: Integration specs use `route()` with `Cypress.env('routePrefix')`**

Run:

```bash
cd "$(git rev-parse --show-toplevel)"
rg -n "route\\(|routePrefix" cypress/integration/*.js
```

Expected: both smoke files define `route` and call `cy.visit(route(...))`.

- **Step 5: Commit**

No commit if read-only verification only.

---

### Task 4: Verify §3.6 — artifacts always upload with matrix-specific names

**Files:**

- Read-only: `.github/workflows/e2e.yml`
- **Step 1: List artifact steps**

Run:

```bash
rg -n "upload-artifact|name: cypress-artifacts|name: bench-serve" "$(git rev-parse --show-toplevel)/.github/workflows/e2e.yml"
```

Expected: two `actions/upload-artifact@v4` steps with `if: always()`, names including `frappe${{ matrix.frappe_version }}`, paths for `cypress/videos`, `cypress/screenshots`, and `/tmp/bench-serve-*.log`.

- **Step 2: Commit**

No commit if verification only.

---

### Task 5: Design spec — fix References markdown and document Frappe 16 route-prefix choice

**Files:**

- Modify: `docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md`

**Context:** §1 References line is malformed Markdown. §3.3’s table lists `desk` for Frappe 16; the implemented matrix uses `app` for both rows with an inline YAML comment (`# Use app routes on v16 for Cypress; /desk paths differ and broke smoke.`). Record that explicitly in the spec so future readers do not “fix” the matrix back to `desk` without revisiting Cypress selectors/routes.

- **Step 1: Replace the broken References line (around line 4)** with:

```markdown
**References:** [`e2e.yml` (production-entry-app)](https://github.com/Guru107/production-entry-app/blob/develop/.github/workflows/e2e.yml), [`run_ephemeral_e2e.sh` (production-entry-app)](https://github.com/Guru107/production-entry-app/blob/develop/scripts/run_ephemeral_e2e.sh)
```

- **Step 2: After the §3.3 table (after the `Route prefix for Cypress` row), add a short paragraph:**

```markdown
**Implementation note (asn_module):** The GitHub Actions matrix sets `frappe_route_prefix` to `app` for both Frappe 15 and 16 because `/desk` URLs broke smoke tests on v16; the table above documents the original *reference-app* convention. Revisit `desk` for v16 only after validating routes and selectors under `bench run-ui-tests`.
```

- **Step 3: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md
git commit -m "docs(spec): fix E2E workflow references and note v16 route prefix"
```

---

### Task 6: Acceptance — green workflows and branch protection

**Files:**

- None (operations + optional local run)
- **Step 1: Push branch and confirm Actions**

After pushing to GitHub, open the PR **Checks** tab (or **Actions** → workflow **E2E**). Confirm both matrix jobs complete for `pull_request` (or `workflow_dispatch` with `smoke`).

- **Step 2: Confirm scheduled workflow uses `ci` mode**

In `.github/workflows/e2e.yml`, the `Run Cypress E2E` step must set `MODE="ci"` when `github.event_name == 'schedule'` (already implemented). Nightly run is optional to wait for; code inspection counts for plan completion if schedule has not fired yet.

- **Step 3: Optional local smoke (developer workstation)**

Requires a running MariaDB reachable with `DB_ROOT_PASSWORD`, and a bench at `BENCH_ROOT` (or default sibling `bench16`). Example:

```bash
cd "$(git rev-parse --show-toplevel)"
export BENCH_ROOT="$HOME/frappe-bench"
export DB_ROOT_PASSWORD="your_root_password"
export FRAPPE_ROUTE_PREFIX=app
./scripts/run_ephemeral_e2e.sh smoke
```

Expected: Cypress exits `0`; script drops the ephemeral site in `cleanup`.

- **Step 4: Branch protection**

In GitHub: **Settings → Rules → Rulesets** (or **Branches → Branch protection rules**) for the default branch. Add required status checks whose names match the `**e2e.yml` job `name`** after a green run, e.g. `E2E (Frappe 15 / ERPNext 15)` and `E2E (Frappe 16 / ERPNext 16)` — copy the **exact** strings from the workflow run UI.

- **Step 5: Commit**

No commit unless workflow YAML renames jobs for clearer protection strings.

---

### Task 7 (escape hatch only): Electron fails — switch to Chrome

**Files:**

- Modify: `.github/workflows/e2e.yml` (add Chrome install step before `Run Cypress E2E`)
- Modify: `scripts/run_ephemeral_e2e.sh` (or workflow `env`) — only if bench accepts `--browser chrome` without extra flags

**Trigger:** `e2e.yml` fails on both matrix rows with Electron-specific errors.

- **Step 1: Add Chrome to the runner (workflow snippet)**

Insert before `Run Cypress E2E`:

```yaml
      - name: Install Chrome for Cypress
        run: |
          sudo apt-get update
          sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
```

- **Step 2: Change test invocation** in `scripts/run_ephemeral_e2e.sh` inside the `smoke | ci)` branch from:

```bash
bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron
```

to:

```bash
bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser chrome
```

- **Step 3: Re-run E2E workflow** and confirm green or iterate with `CYPRESS_BROWSER` / Frappe docs.
- **Step 4: Commit**

```bash
git add .github/workflows/e2e.yml scripts/run_ephemeral_e2e.sh
git commit -m "ci(e2e): fall back to Chrome when Electron fails on runners"
```

---

## Self-review

**1. Spec coverage**


| Spec section       | Plan tasks                     |
| ------------------ | ------------------------------ |
| §1 Goals           | File map + Task 2–3            |
| §3 Workflow        | Tasks 3–4, 6                   |
| §4 Script          | Task 1 (+ Task 7 escape hatch) |
| §5 Cypress routing | Task 3                         |
| §6 CI changes      | Task 2                         |
| §7 Risks / policy  | Tasks 6–7, spec note in Task 5 |
| §8 Acceptance      | Tasks 2–4, 6                   |


**2. Placeholder scan**

No `TBD`, `TODO`, or “similar to Task N”; code blocks contain concrete shell/YAML/Markdown.

**3. Type / naming consistency**

- `E2E_MODE` values: `smoke` and `ci` only (matches `case` in `run_ephemeral_e2e.sh`).
- Artifact name pattern: `cypress-artifacts-frappe${{ matrix.frappe_version }}` and `bench-serve-frappe${{ matrix.frappe_version }}` (numeric `15`/`16`).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-04-asn-module-e2e-workflow.md`.

**1. Subagent-driven (recommended)** — Dispatch a fresh subagent per task, review between tasks (superpowers:subagent-driven-development).

**2. Inline execution** — Run tasks in this session with checkpoints (superpowers:executing-plans).

Which approach do you want?