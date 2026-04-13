from hypothesis import given
from hypothesis import strategies as st


def _identity(x):
    return x


@given(st.text())
def test_property_harness_smoke_identity(text_value):
    assert _identity(text_value) == text_value
