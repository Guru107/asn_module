"""Aggregate property tests for single-pass CI execution with coverage.

Frappe's test runner handles explicit module targets most reliably. Running
one aggregate module ensures coverage is produced in one invocation.
"""

from asn_module.property_tests.test_asn_new_services_properties import TestPropertyHarness
from asn_module.property_tests.test_scan_code_properties import TestScanCodeProperties
from asn_module.property_tests.test_token_properties import TestTokenProperties

__all__ = [
	"TestPropertyHarness",
	"TestScanCodeProperties",
	"TestTokenProperties",
]
