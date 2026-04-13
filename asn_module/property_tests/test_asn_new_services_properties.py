from hypothesis import given
from hypothesis import settings as hypothesis_settings

from asn_module.property_tests import settings as property_settings
from asn_module.property_tests.strategies import scan_text


def _identity(x):
    return x


@given(scan_text)
def test_property_harness_smoke_identity(text_value):
    assert _identity(text_value) == text_value
    expected_max_examples = 80 if property_settings.PROFILE == "ci" else 300
    assert hypothesis_settings.default.max_examples == expected_max_examples
    assert hypothesis_settings.default.deadline is None
