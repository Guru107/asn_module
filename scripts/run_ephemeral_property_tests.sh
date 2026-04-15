#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

property_modules=(
	"asn_module.property_tests.test_asn_new_services_properties"
	"asn_module.property_tests.test_scan_code_properties"
	"asn_module.property_tests.test_token_properties"
)

for module in "${property_modules[@]}"; do
	CI=true bash "$APP_ROOT/scripts/run_ephemeral_python_tests.sh" "$module"
done
