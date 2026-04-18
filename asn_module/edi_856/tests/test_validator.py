from pathlib import Path
from unittest import TestCase

from asn_module.edi_856.parser import parse_edi

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestValidate856Baseline(TestCase):
	def test_missing_bsn_produces_required_segment_error(self):
		from asn_module.edi_856.validator import validate_856_baseline

		parsed = parse_edi((FIXTURES_DIR / "invalid_missing_bsn.txt").read_text())
		result = validate_856_baseline(parsed)

		self.assertFalse(result.is_compliant)
		self.assertEqual([finding.rule_id for finding in result.errors], ["SEG-BSN-REQ-001"])
		self.assertEqual(result.errors[0].segment_tag, "BSN")
		self.assertEqual(result.errors[0].severity, "error")
		self.assertIn("BSN", result.errors[0].message)
		self.assertEqual(result.errors[0].fix_hint, "Add a BSN segment after ST.")

	def test_st_se_control_mismatch_produces_control_error(self):
		from asn_module.edi_856.validator import validate_856_baseline

		parsed = parse_edi("ST*856*0001~BSN*00*12345~HL*1**S~CTT*1~SE*5*9999~")
		result = validate_856_baseline(parsed)

		self.assertFalse(result.is_compliant)
		self.assertEqual([finding.rule_id for finding in result.errors], ["CNT-SE02-ST02-MATCH-001"])
		self.assertEqual(result.errors[0].segment_tag, "SE")
		self.assertEqual(result.errors[0].segment_index, 4)
		self.assertEqual(result.errors[0].element_index, 1)
		self.assertEqual(result.errors[0].fix_hint, "Set SE02 to match ST02.")
