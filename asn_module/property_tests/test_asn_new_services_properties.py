from hypothesis import given
from hypothesis import strategies as st
from hypothesis import settings as hypothesis_settings
from frappe.tests import UnitTestCase
from frappe.utils import flt

from asn_module.property_tests import settings as property_settings
from asn_module.property_tests.strategies import scan_text
from asn_module.templates.pages.asn_new_services import PortalValidationError
from asn_module.templates.pages.asn_new_services import normalize_group_field
from asn_module.templates.pages.asn_new_services import normalize_group_value
from asn_module.templates.pages.asn_new_services import parse_positive_qty


def _identity(x):
	return x


positive_qty_text = st.floats(
	min_value=1e-6,
	allow_nan=False,
	allow_infinity=False,
).map(str)

non_positive_qty_text = st.one_of(
	st.just("0"),
	st.floats(max_value=0, allow_nan=False, allow_infinity=False).map(str),
)

group_value_text = st.one_of(
	st.none(),
	st.text(max_size=128),
)

numeric_invoice_amount_text = st.decimals(
	allow_nan=False,
	allow_infinity=False,
	places=6,
).map(str)


class TestPropertyHarness(UnitTestCase):
	@given(scan_text)
	def test_property_harness_smoke_identity(self, text_value):
		self.assertEqual(_identity(text_value), text_value)
		expected_max_examples = 80 if property_settings.PROFILE == "ci" else 300
		self.assertEqual(hypothesis_settings.default.max_examples, expected_max_examples)
		self.assertIsNone(hypothesis_settings.default.deadline)

	@given(positive_qty_text)
	def test_parse_positive_qty_accepts_positive_floats(self, qty_text):
		parsed = parse_positive_qty(qty_text, row_number=1, field="qty")
		self.assertGreater(parsed, 0)
		self.assertEqual(parsed, flt(qty_text))

	@given(non_positive_qty_text)
	def test_parse_positive_qty_rejects_non_positive_values(self, qty_text):
		with self.assertRaises(PortalValidationError):
			parse_positive_qty(qty_text, row_number=1, field="qty")

	@given(group_value_text)
	def test_normalize_group_value_is_idempotent(self, raw_value):
		normalized = normalize_group_value(raw_value)
		self.assertEqual(normalize_group_value(normalized), normalized)

	@given(numeric_invoice_amount_text)
	def test_supplier_invoice_amount_normalization_preserves_numeric_equivalence(self, raw_value):
		normalized = normalize_group_field("supplier_invoice_amount", raw_value)
		canonical = str(flt(raw_value))
		self.assertEqual(normalized, canonical)
		self.assertEqual(flt(normalized), flt(raw_value))
