#!/usr/bin/env bash
# Ephemeral bench site + bench serve + Cypress (smoke | ci). See docs/superpowers/specs/2026-04-04-asn-module-e2e-workflow-design.md

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../bench16" && pwd)}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-admin}"
RUN_ID="${EPHEMERAL_SITE_RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"
SITE_NAME="asn-e2e-${RUN_ID//[^a-zA-Z0-9]/}"
E2E_MODE="${1:-smoke}"
SERVE_PORT="${EPHEMERAL_E2E_PORT:-}"
SERVER_PID=""
PREVIOUS_SITE=""
SERVE_LOG="/tmp/bench-serve-${RUN_ID}.log"

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "DB_ROOT_PASSWORD is required for ephemeral site creation and teardown." >&2
	exit 1
fi

if [ -z "$SERVE_PORT" ] && { [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]; }; then
	SERVE_PORT="18002"
fi
if [ -z "$SERVE_PORT" ]; then
	SERVE_PORT="8000"
fi

cleanup() {
	local exit_code=$?
	set +e
	if [ -n "${SERVER_PID:-}" ]; then
		kill "$SERVER_PID" >/dev/null 2>&1 || true
		wait "$SERVER_PID" >/dev/null 2>&1 || true
	fi
	if [ -n "${SITE_NAME:-}" ] && [ -d "$BENCH_ROOT/sites/$SITE_NAME" ]; then
		echo "Dropping ephemeral site $SITE_NAME"
		cd "$BENCH_ROOT" || exit "$exit_code"
		bench drop-site "$SITE_NAME" --force --no-backup --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD"
	fi
	if [ -n "${PREVIOUS_SITE:-}" ] && [ -d "$BENCH_ROOT/sites/$PREVIOUS_SITE" ]; then
		cd "$BENCH_ROOT" || exit "$exit_code"
		bench use "$PREVIOUS_SITE" >/dev/null 2>&1 || true
	fi
	exit "$exit_code"
}

trap cleanup EXIT

cd "$BENCH_ROOT"

if [ -f "$BENCH_ROOT/sites/currentsite.txt" ]; then
	PREVIOUS_SITE="$(cat "$BENCH_ROOT/sites/currentsite.txt")"
fi

bench new-site "$SITE_NAME" --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$EPHEMERAL_ADMIN_PASSWORD"
bench --site "$SITE_NAME" install-app erpnext
bench --site "$SITE_NAME" install-app asn_module
bench build --app asn_module

set +e
fixtures_output="$(
	bench --site "$SITE_NAME" execute erpnext.setup.setup_wizard.operations.install_fixtures.install --args '["India"]' 2>&1
)"
fixtures_exit=$?
set -e

if [ "$fixtures_exit" -ne 0 ]; then
	if printf '%s' "$fixtures_output" | grep -q "NestedSetRecursionError\|Item cannot be added to its own descendants"; then
		echo "Warning: setup wizard fixture install hit nested-set recursion; continuing with test bootstrap."
	else
		printf '%s\n' "$fixtures_output" >&2
		exit "$fixtures_exit"
	fi
fi

bench --site "$SITE_NAME" set-config allow_tests true
bench --site "$SITE_NAME" execute asn_module.utils.test_setup.before_tests

bench use "$SITE_NAME"

echo "Adding hosts entry for Cypress baseUrl..."
echo "127.0.0.1 ${SITE_NAME}" | sudo tee -a /etc/hosts >/dev/null

echo "Starting Frappe (port ${SERVE_PORT}, log ${SERVE_LOG})..."
nohup bench --site "$SITE_NAME" serve --port "$SERVE_PORT" --noreload >"$SERVE_LOG" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 45); do
	if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
		cat "$SERVE_LOG" >&2 || true
		exit 1
	fi
	if curl -sSf "http://${SITE_NAME}:${SERVE_PORT}/api/method/frappe.ping" >/dev/null 2>&1; then
		ready=1
		break
	fi
	sleep 2
done

if [ "$ready" != 1 ]; then
	echo "Frappe server did not become ready in time." >&2
	cat "$SERVE_LOG" >&2 || true
	exit 1
fi

export FRAPPE_ROUTE_PREFIX="${FRAPPE_ROUTE_PREFIX:-app}"
export BENCH_ROOT
export EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-admin}"
export CYPRESS_adminPassword="${CYPRESS_adminPassword:-$EPHEMERAL_ADMIN_PASSWORD}"

echo "Running Cypress (mode=${E2E_MODE})..."
case "$E2E_MODE" in
smoke | ci)
	bench --site "$SITE_NAME" run-ui-tests asn_module --headless --browser electron
	;;
*)
	echo "Unknown mode: $E2E_MODE (use smoke or ci)" >&2
	exit 1
	;;
esac
