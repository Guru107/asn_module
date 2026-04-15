#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CI=true bash "$APP_ROOT/scripts/run_ephemeral_python_tests.sh" asn_module.property_tests
