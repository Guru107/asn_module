#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../bench16" && pwd)}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-admin}"
RUN_ID="${EPHEMERAL_SITE_RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"
SITE_NAME="asn-py-${RUN_ID//[^a-zA-Z0-9]/}"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
	echo "SITE_NAME=$SITE_NAME" >> "$GITHUB_OUTPUT"
fi

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "DB_ROOT_PASSWORD is required for ephemeral site creation and teardown." >&2
	exit 1
fi

cleanup() {
	local exit_code=$?
	set +e
	if [ -n "${SITE_NAME:-}" ] && [ -d "$BENCH_ROOT/sites/$SITE_NAME" ]; then
		if [ "${CI:-}" = "true" ] && [ -f "$BENCH_ROOT/sites/$SITE_NAME/coverage.xml" ]; then
			mkdir -p "$APP_ROOT"
			cp "$BENCH_ROOT/sites/$SITE_NAME/coverage.xml" "$APP_ROOT/"
		fi
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

bench --site "$SITE_NAME" set-config allow_tests true
# `before_tests` establishes ERPNext defaults for app tests; avoid replaying
# setup-wizard fixtures because nested-set conflicts are noisy and non-actionable.
bench --site "$SITE_NAME" execute asn_module.utils.test_setup.before_tests

run_tests_cmd=("$(which bench)" --site "$SITE_NAME" run-tests)
if [ "${ERPNEXT_VERSION:-}" = "16" ]; then
	run_tests_cmd+=(--lightmode)
fi

if [ "$#" -gt 0 ]; then
	run_tests_cmd+=(--module "$1")
else
	run_tests_cmd+=(--app asn_module)
fi

# Run tests as the exit gate and propagate the exact exit status. Coverage
# collection via coverage.py subprocess injection is unreliable with bench
# (Frappe spawns workers); CI uses Frappe's --coverage flag instead.
if [ "${CI:-}" = "true" ]; then
	run_tests_cmd+=(--coverage)
fi

set +e
"${run_tests_cmd[@]}"
test_exit=$?
set -e

if [ $test_exit -ne 0 ]; then
	echo "Tests failed with exit code $test_exit" >&2
fi
exit $test_exit
