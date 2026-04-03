# Read CLAUDE.md

## Cursor Cloud specific instructions

### Environment layout

- **Frappe bench**: `/home/ubuntu/frappe-bench` (Frappe v16 + ERPNext v16 + asn_module soft-linked from `/workspace`)
- **Site**: `dev.localhost` (admin password: `admin`, developer_mode enabled, allow_tests enabled)
- **Python**: 3.14 (from `ppa:deadsnakes/ppa`); the bench venv lives at `/home/ubuntu/frappe-bench/env`
- **Node**: 24 via nvm (`nvm use 24`); yarn is available globally

### Starting services

Before running `bench start` or tests, ensure MariaDB and Redis are up:

```bash
sudo service mariadb start
sudo service redis-server start
redis-server --port 13000 --daemonize yes
redis-server --port 11000 --daemonize yes
```

Redis must listen on ports **13000** (cache + socketio) and **11000** (queue) — these match the bench `common_site_config.json`.

### Running the dev server

```bash
cd /home/ubuntu/frappe-bench
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use 24
bench start
```

The app serves at `http://localhost:8000`. Login: `Administrator` / `admin`.

### Linting

```bash
cd /workspace
ruff check asn_module/        # Python lint
npx eslint asn_module/ --quiet # JS lint
```

See `docs/ProjectOverview.md` for full linting/formatting commands.

### Running tests

```bash
cd /home/ubuntu/frappe-bench
export PATH="$HOME/.local/bin:$PATH"
bench --site dev.localhost run-tests --app asn_module --lightmode
```

Use `--lightmode` to avoid ERPNext test-record bootstrapping errors (fiscal year overlap). The ephemeral test script at `scripts/run_ephemeral_python_tests.sh` is intended for CI only.

### Gotchas

- Frappe v16 **requires Python ≥ 3.14**. The system Python 3.12 will not work for bench operations.
- The `bench init` may fail with a crontab error; this is non-critical. Install `cron` package if needed.
- When running tests without `--lightmode`, ERPNext's test-record bootstrap may throw a fiscal-year overlap error after all asn_module tests pass. This is harmless to asn_module tests but causes a non-zero exit code.
- The app is installed via `bench get-app --soft-link /workspace`, so code changes in `/workspace` are immediately reflected.
- `bench build --app asn_module` rebuilds frontend assets. The `bench start` watcher auto-rebuilds JS/CSS on save.
