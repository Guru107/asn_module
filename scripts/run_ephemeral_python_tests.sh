#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../bench16" && pwd)}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-admin}"
RUN_ID="${EPHEMERAL_SITE_RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"
SITE_NAME="asn-py-${RUN_ID//[^a-zA-Z0-9]/}"

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "DB_ROOT_PASSWORD is required for ephemeral site creation and teardown." >&2
	exit 1
fi

cleanup() {
	local exit_code=$?
	set +e
	if [ -n "${SITE_NAME:-}" ] && [ -d "$BENCH_ROOT/sites/$SITE_NAME" ]; then
		echo "Dropping ephemeral site $SITE_NAME"
		cd "$BENCH_ROOT" || exit "$exit_code"
		bench drop-site "$SITE_NAME" --force --no-backup --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD"
	fi
	exit "$exit_code"
}

trap cleanup EXIT

cd "$BENCH_ROOT"

bench new-site "$SITE_NAME" --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$EPHEMERAL_ADMIN_PASSWORD"
bench --site "$SITE_NAME" install-app erpnext
bench --site "$SITE_NAME" install-app asn_module
bench build --app asn_module

# ERPNext fixture install can intermittently fail in CI with nested-set recursion
# while base records already exist. Ignore only that known transient and fail for
# any other setup error.
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

run_tests_cmd=("$(which bench)" --site "$SITE_NAME" run-tests --app asn_module)
if [ "${ERPNEXT_VERSION:-}" = "16" ]; then
	run_tests_cmd+=(--lightmode)
fi

if [ "$#" -gt 0 ]; then
	run_tests_cmd+=(--module "$1")
fi

# Run tests as the exit gate — always exit 0 from this script so CI uses
# the test result as the authoritative signal. Coverage collection via
# coverage.py subprocess injection is unreliable with bench (Frappe spawns
# workers); CI uses Frappe's --coverage flag instead.
"${run_tests_cmd[@]}"
