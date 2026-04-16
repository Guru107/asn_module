"""Aggregate property tests for single-pass CI execution with coverage.

This module is intentionally not named with a ``test_`` prefix so it is not
auto-discovered during full app test runs.
"""

from asn_module.property_tests.test_asn_new_services_properties import TestPropertyHarness
from asn_module.property_tests.test_scan_code_properties import TestScanCodeProperties
from asn_module.property_tests.test_token_properties import TestTokenProperties

__all__ = [
	"TestPropertyHarness",
	"TestScanCodeProperties",
	"TestTokenProperties",
]
