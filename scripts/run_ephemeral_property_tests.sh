#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_COVERAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/asn-property-coverage.XXXXXX")"

property_modules=(
	"asn_module.property_tests.test_asn_new_services_properties"
	"asn_module.property_tests.test_scan_code_properties"
	"asn_module.property_tests.test_token_properties"
)

cleanup() {
	rm -rf "$TMP_COVERAGE_DIR"
}

trap cleanup EXIT

module_index=0
for module in "${property_modules[@]}"; do
	module_index=$((module_index + 1))
	coverage_data_file="$TMP_COVERAGE_DIR/.coverage.$module_index"
	coverage_xml_file="$TMP_COVERAGE_DIR/coverage.$module_index.xml"
	CI=true \
		COVERAGE_XML_OUTPUT="$coverage_xml_file" \
		COVERAGE_DATA_OUTPUT="$coverage_data_file" \
		bash "$APP_ROOT/scripts/run_ephemeral_python_tests.sh" "$module"
done

cd "$APP_ROOT"
if ! compgen -G "$TMP_COVERAGE_DIR/.coverage.*" >/dev/null; then
	echo "No raw coverage data files were collected from property test runs." >&2
	exit 1
fi

COVERAGE_FILE="$TMP_COVERAGE_DIR/.coverage.combined" coverage combine "$TMP_COVERAGE_DIR"/.coverage.*
COVERAGE_FILE="$TMP_COVERAGE_DIR/.coverage.combined" coverage xml -o "$APP_ROOT/coverage.xml"
