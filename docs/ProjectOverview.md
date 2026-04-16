# Project Overview

This is a **Frappe framework** custom app called `asn_module`. It follows standard Frappe app conventions and is managed via the `bench` CLI. The app targets Python 3.14 and Frappe v16.

## Bench server setups

### Frappe Version 16 and ERPNext Version 16
    Path: /Users/gurudattkulkarni/Workspace/bench16
    site_name: frappe16.localhost
    Run
    ```bash
    nvm use
    source .venv/bin/activate
    ```
### Frappe Version 15 and ERPNext Version 15
    Path: /Users/gurudattkulkarni/Workspace/bench15
    site_name: development.localhost

    Run
    ```bash
    nvm use
    source .venv/bin/activate
    ```

## Application Setup

This application is installed in both the bench directories using a sym-linked approach using below command

 ```bash
    bench get-app --soft-link /Users/gurudattkulkarni/Workspace/asn_module
    bench install-app asn_module
```

### Running Tests
```bash
bench --site <site_name> run-tests --app asn_module
# Single test module:
bench --site <site_name> run-tests --module asn_module.<module_path>
# Single test:
bench --site <site_name> run-tests --module asn_module.<module_path> --test <test_name>
```

### Property-Based Tests
Use the `HYPOTHESIS_PROFILE` env var to switch between CI-sized and deeper local runs.

```bash
# Phase 1: run one property module locally
HYPOTHESIS_PROFILE=local bench --site frappe16.localhost run-tests \
  --module asn_module.property_tests.test_asn_new_services_properties \
  --lightmode

# Full property suite: run each module explicitly
for m in \
  asn_module.property_tests.test_asn_new_services_properties \
  asn_module.property_tests.test_scan_code_properties \
  asn_module.property_tests.test_token_properties; do
  HYPOTHESIS_PROFILE=local bench --site frappe16.localhost run-tests --module "$m" --lightmode
done

# CI-style profile for local reproduction
HYPOTHESIS_PROFILE=ci bench --site frappe16.localhost run-tests \
  --module asn_module.property_tests.test_asn_new_services_properties \
  --lightmode
```

Notes:
- `bench --site frappe16.localhost run-tests --module asn_module.property_tests --lightmode` returns no tests ran in this repo; run each property module explicitly.
- The CI job uses the `ci` profile. Local debugging can use `local` to increase examples.

Triage guidance:
- Let Hypothesis shrink the failure first. Keep the minimized counterexample it prints.
- Re-run the single failing module with the same `HYPOTHESIS_PROFILE` to confirm it is reproducible.
- If the failure is real, add a deterministic regression test next to the affected code and keep the property test as the fuzzing guard.
- If the failure is only caused by unrealistic input, tighten the strategy bounds rather than asserting on a larger surface than the code actually guarantees.

For running E2E Tests use Cypress
```bash
Usage: bench run-ui-tests [OPTIONS] APP [CYPRESSARGS]...

  Run UI tests

Options:
  --headless          Run UI Test in headless mode
  --parallel          Run UI Test in parallel mode
  --with-coverage     Generate coverage report
  --browser TEXT      Browser to run tests in
  --spec TEXT         Spec file to run
  --ci-build-id TEXT
  --help              Show this message and exit.
```

### Linting & Formatting
```bash
# Python linting/formatting (ruff)
ruff check asn_module/
ruff format asn_module/

# JavaScript linting
npx eslint asn_module/

# Run all pre-commit hooks
pre-commit run --all-files
```

### Pre-commit Setup
```bash
pre-commit install
```

## Code Style

- **Python**: Uses `ruff` with tab indentation, double quotes, 110 char line length. Config in `pyproject.toml`.
- **JavaScript**: Uses `eslint` + `prettier`. Frappe globals (`frappe`, `cur_frm`, `__`, etc.) are pre-configured in `.eslintrc`.

## Architecture

This is a standard Frappe app structure:

- `asn_module/hooks.py` — App-level hooks (document events, scheduled tasks, includes, etc.)
- `asn_module/modules.txt` — Declares the "ASN Module" module
- `asn_module/asn_module/` — Module directory containing doctypes, reports, pages, etc.
- `asn_module/templates/` — Web templates (Jinja)
- `asn_module/patches/` — Data migration patches (listed in `patches.txt`)
- `asn_module/public/` — Static assets (JS, CSS, images)
- `asn_module/config/` — App configuration (desktop icons, docs)

New doctypes go under `asn_module/asn_module/doctype/<doctype_name>/`. Each doctype folder contains a JSON definition, Python controller, and optional JS client script.

## CI

- **CI workflow** (`.github/workflows/ci.yml`): Runs on push to `main` and PRs. Sets up MariaDB + Redis, installs Frappe bench, and runs server tests.
- **Linters workflow** (`.github/workflows/linter.yml`): Runs pre-commit hooks, Frappe Semgrep rules, and `pip-audit` on PRs.
