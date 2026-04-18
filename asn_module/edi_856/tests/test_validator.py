from pathlib import Path
from unittest import TestCase

from asn_module.edi_856.parser import parse_edi
from asn_module.edi_856.rules_4010 import (
	CNT_CTT01_HL_COUNT_001,
	CNT_SE01_SCOPE_COUNT_001,
	CNT_SE02_ST02_MATCH_001,
	ELM_BSN01_REQ_001,
	ELM_BSN02_REQ_001,
	ELM_BSN03_REQ_001,
	ELM_CTT01_NUMERIC_001,
	ELM_SE02_REQ_001,
	ELM_ST01_856_001,
	ELM_ST02_REQ_001,
	FMT_BSN03_DATE_001,
	HL_HL01_REQ_001,
	HL_HL01_UNIQUE_001,
	HL_PARENT_REF_001,
	ORD_BSN_HL_001,
	ORD_HL_CTT_001,
	SEG_BSN_CARD_001,
	SEG_BSN_REQ_001,
	SEG_CTT_CARD_001,
	SEG_CTT_REQ_001,
	SEG_HL_REQ_001,
	SEG_OUTSIDE_SCOPE_001,
	SEG_SE_CARD_001,
	SEG_SE_REQ_001,
	SEG_ST_CARD_001,
	SEG_ST_REQ_001,
)
from asn_module.edi_856.validator import validate_856_baseline

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VALID_PAYLOAD = (FIXTURES_DIR / "valid_856_minimal.txt").read_text()


class TestValidate856Baseline(TestCase):
	def error_rule_ids(self, result):
		return [finding.rule_id for finding in result.errors]

	def error_for(self, result, rule_id):
		return next(finding for finding in result.errors if finding.rule_id == rule_id)

	def test_accepts_raw_edi_string_input(self):
		result = validate_856_baseline(VALID_PAYLOAD)

		self.assertTrue(result.is_compliant)
		self.assertEqual(result.errors, [])
		self.assertEqual(result.warnings, [])

	def test_selects_first_856_transaction_set_in_mixed_interchange(self):
		payload = (
			"ISA*00*          *00*          *ZZ*SEND*ZZ*RECV*260418*1200*U*00401*000000001*0*T*:~"
			"GS*SH*SENDER*RECEIVER*20260418*1200*1*X*004010~"
			"ST*850*0009~BEG*00*SA*PO123~SE*3*0009~"
			"ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~"
			"GE*2*1~IEA*1*000000001~"
		)

		result = validate_856_baseline(payload)

		self.assertTrue(result.is_compliant)
		self.assertNotIn(SEG_OUTSIDE_SCOPE_001, self.error_rule_ids(result))
		self.assertNotIn(SEG_ST_CARD_001, self.error_rule_ids(result))
		self.assertNotIn(ELM_ST01_856_001, self.error_rule_ids(result))
		self.assertNotIn(SEG_BSN_REQ_001, self.error_rule_ids(result))
		self.assertEqual(result.computed_metrics["has_st"], 1)
		self.assertEqual(result.computed_metrics["has_bsn"], 1)
		self.assertEqual(result.computed_metrics["has_se"], 1)

	def test_mixed_interchange_has_metrics_use_selected_856_scope(self):
		payload = (
			"ST*850*0009~BEG*00*SA*PO123~SE*3*0009~"
			"ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~"
		)

		result = validate_856_baseline(payload)

		self.assertFalse(result.is_compliant)
		self.assertEqual(result.computed_metrics["has_st"], 1)
		self.assertEqual(result.computed_metrics["has_bsn"], 1)
		self.assertEqual(result.computed_metrics["has_se"], 0)

	def test_non_856_transaction_fails_st01_rule(self):
		result = validate_856_baseline(
			"ST*850*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~"
		)

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, ELM_ST01_856_001)
		self.assertEqual(finding.segment_tag, "ST")
		self.assertEqual(finding.element_index, 1)

	def test_business_segment_after_se_is_non_compliant(self):
		result = validate_856_baseline(
			parse_edi("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~N1*SH*ACME~")
		)

		self.assertFalse(result.is_compliant)
		self.assertIn(SEG_OUTSIDE_SCOPE_001, self.error_rule_ids(result))

	def test_envelope_tags_outside_scope_are_allowed(self):
		result = validate_856_baseline(
			parse_edi(
				"ISA*00*          *00*          *ZZ*SEND*ZZ*RECV*260418*1200*U*00401*000000001*0*T*:~"
				"GS*SH*SENDER*RECEIVER*20260418*1200*1*X*004010~"
				"ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~"
				"GE*1*1~IEA*1*000000001~"
			)
		)

		self.assertTrue(result.is_compliant)

	def test_missing_segment_index_uses_nearest_required_neighbor(self):
		result = validate_856_baseline(parse_edi("HL*1**S~ST*856*0001~CTT*1~SE*4*0001~"))

		missing_bsn = self.error_for(result, SEG_BSN_REQ_001)
		self.assertEqual(missing_bsn.segment_index, 2)

	def test_missing_st_validates_in_place_without_outside_scope_noise(self):
		result = validate_856_baseline("BSN*00*12345*20260418~HL*1**S~CTT*1~SE*4*0001~")

		self.assertFalse(result.is_compliant)
		self.assertIn(SEG_ST_REQ_001, self.error_rule_ids(result))
		self.assertNotIn(SEG_OUTSIDE_SCOPE_001, self.error_rule_ids(result))
		self.assertEqual(result.computed_metrics["has_st"], 0)
		self.assertEqual(result.computed_metrics["has_se"], 1)

	def test_st02_and_se02_are_required(self):
		result = validate_856_baseline("ST*856~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5~")

		self.assertFalse(result.is_compliant)
		self.assertEqual(self.error_for(result, ELM_ST02_REQ_001).element_index, 2)
		self.assertEqual(self.error_for(result, ELM_SE02_REQ_001).element_index, 2)

	def test_control_mismatch_is_not_reported_when_either_control_is_missing(self):
		missing_st02 = validate_856_baseline("ST*856~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~")
		missing_se02 = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5~")

		self.assertNotIn(CNT_SE02_ST02_MATCH_001, self.error_rule_ids(missing_st02))
		self.assertNotIn(CNT_SE02_ST02_MATCH_001, self.error_rule_ids(missing_se02))

	def test_bsn_required_elements_are_enforced(self):
		result = validate_856_baseline("ST*856*0001~BSN***~HL*1**S~CTT*1~SE*5*0001~")

		self.assertFalse(result.is_compliant)
		self.assertIn(ELM_BSN01_REQ_001, self.error_rule_ids(result))
		self.assertIn(ELM_BSN02_REQ_001, self.error_rule_ids(result))
		self.assertIn(ELM_BSN03_REQ_001, self.error_rule_ids(result))

	def test_bsn03_requires_ccyymmdd_format(self):
		result = validate_856_baseline("ST*856*0001~BSN*00*12345*2026-04-18~HL*1**S~CTT*1~SE*5*0001~")

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, FMT_BSN03_DATE_001)
		self.assertEqual(finding.segment_tag, "BSN")
		self.assertEqual(finding.element_index, 3)

	def test_invalid_hl_parent_reference_fails_hierarchy_rule(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~HL*1*99*S~CTT*1~SE*5*0001~"
		)

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, HL_PARENT_REF_001)
		self.assertEqual(finding.segment_tag, "HL")
		self.assertEqual(finding.segment_index, 2)
		self.assertEqual(finding.element_index, 2)

	def test_hl01_must_be_non_empty_and_unique(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~HL**~HL*1**S~HL*1*1*I~CTT*1~SE*7*0001~"
		)

		self.assertFalse(result.is_compliant)
		self.assertIn(HL_HL01_REQ_001, self.error_rule_ids(result))
		self.assertIn(HL_HL01_UNIQUE_001, self.error_rule_ids(result))

	def test_ctt01_must_be_numeric(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*ABC~SE*5*0001~"
		)

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, ELM_CTT01_NUMERIC_001)
		self.assertEqual(finding.segment_tag, "CTT")
		self.assertEqual(finding.element_index, 1)

	def test_ctt01_compares_against_item_hl_count_when_present(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~HL*1**S~HL*2*1*O~HL*3*2*I~CTT*2~SE*7*0001~"
		)

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, CNT_CTT01_HL_COUNT_001)
		self.assertIn("item-level HL count", finding.fix_hint)

	def test_ctt01_falls_back_to_total_hl_count_when_no_item_hls_exist(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~HL*1**S~HL*2*1*O~CTT*1~SE*6*0001~"
		)

		self.assertFalse(result.is_compliant)
		finding = self.error_for(result, CNT_CTT01_HL_COUNT_001)
		self.assertIn("total HL count", finding.fix_hint)

	def test_se01_segment_count_mismatch_pins_metadata_and_reporting(self):
		from asn_module.edi_856.reporting import compliance_result_to_text

		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*4*0001~")

		self.assertFalse(result.is_compliant)
		self.assertEqual(self.error_for(result, CNT_SE01_SCOPE_COUNT_001).segment_index, 4)
		self.assertIn("element=1", compliance_result_to_text(result))

	def test_se02_mismatch_pins_metadata_and_reporting(self):
		from asn_module.edi_856.reporting import compliance_result_to_text

		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*9999~")

		self.assertFalse(result.is_compliant)
		self.assertEqual(self.error_for(result, CNT_SE02_ST02_MATCH_001).element_index, 2)
		self.assertIn("element=2", compliance_result_to_text(result))

	def test_missing_se_produces_required_segment_error(self):
		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~")

		self.assertFalse(result.is_compliant)
		self.assertEqual(self.error_for(result, SEG_SE_REQ_001).segment_index, 4)

	def test_ordering_violations_still_produce_order_errors(self):
		result = validate_856_baseline("ST*856*0001~HL*1**S~BSN*00*12345*20260418~CTT*1~SE*5*0001~")

		self.assertFalse(result.is_compliant)
		self.assertIn(ORD_BSN_HL_001, self.error_rule_ids(result))

	def test_ctt_and_se_ordering_violations_still_produce_order_errors(self):
		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~CTT*1~HL*1**S~SE*5*0001~")

		self.assertFalse(result.is_compliant)
		self.assertIn(ORD_HL_CTT_001, self.error_rule_ids(result))

	def test_missing_hl_and_ctt_produce_required_segment_errors(self):
		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~SE*3*0001~")

		self.assertFalse(result.is_compliant)
		self.assertIn(SEG_HL_REQ_001, self.error_rule_ids(result))
		self.assertIn(SEG_CTT_REQ_001, self.error_rule_ids(result))

	def test_duplicate_singletons_still_produce_cardinality_errors(self):
		result = validate_856_baseline(
			"ST*856*0001~BSN*00*12345*20260418~BSN*00*12346*20260418~HL*1**S~CTT*1~CTT*2~SE*7*0001~SE*1*0002~"
		)

		self.assertFalse(result.is_compliant)
		self.assertIn(SEG_OUTSIDE_SCOPE_001, self.error_rule_ids(result))
		self.assertIn(SEG_BSN_CARD_001, self.error_rule_ids(result))
		self.assertIn(SEG_CTT_CARD_001, self.error_rule_ids(result))
		self.assertIn(SEG_SE_CARD_001, self.error_rule_ids(result))

	def test_trailing_se_outside_primary_scope_still_triggers_se_cardinality_error(self):
		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*5*0001~SE*1*0002~")

		self.assertFalse(result.is_compliant)
		self.assertIn(SEG_OUTSIDE_SCOPE_001, self.error_rule_ids(result))
		self.assertEqual(self.error_for(result, SEG_SE_CARD_001).segment_index, 5)

	def test_computed_metrics_include_hierarchy_and_control_indicators(self):
		result = validate_856_baseline(
			"ST*856*1234~BSN*00*12345*20260418~HL*1**S~HL*2*1*O~HL*3*2*I~CTT*1~SE*7*1234~"
		)

		self.assertTrue(result.is_compliant)
		self.assertEqual(result.computed_metrics["segment_count"], 7)
		self.assertEqual(result.computed_metrics["hl_count"], 3)
		self.assertEqual(result.computed_metrics["item_hl_count"], 1)
		self.assertEqual(result.computed_metrics["max_hl_depth"], 3)
		self.assertEqual(result.computed_metrics["has_st_control"], 1)
		self.assertEqual(result.computed_metrics["has_se_control"], 1)
		self.assertEqual(result.computed_metrics["st_se_control_match"], 1)
		self.assertEqual(result.computed_metrics["st_control_ref"], 1234)
		self.assertEqual(result.computed_metrics["se_control_ref"], 1234)

	def test_reporting_serializes_enriched_metrics_contract(self):
		from asn_module.edi_856.reporting import compliance_result_to_dict, compliance_result_to_text

		result = validate_856_baseline("ST*856*0001~BSN*00*12345*20260418~HL*1**S~CTT*1~SE*4*0001~")
		serialized = compliance_result_to_dict(result)

		self.assertEqual(serialized["is_compliant"], False)
		self.assertEqual(serialized["computed_metrics"], {
			"segment_count": 5,
			"error_count": 1,
			"warning_count": 0,
			"has_st": 1,
			"has_bsn": 1,
			"has_se": 1,
			"hl_count": 1,
			"item_hl_count": 0,
			"max_hl_depth": 1,
			"has_st_control": 1,
			"has_se_control": 1,
			"st_control_ref": 1,
			"se_control_ref": 1,
			"st_se_control_match": 1,
		})
		self.assertEqual(
			serialized["errors"],
			[
				{
					"rule_id": CNT_SE01_SCOPE_COUNT_001,
					"severity": "error",
					"message": "SE01 '4' does not match count '5'.",
					"segment_tag": "SE",
					"segment_index": 4,
					"element_index": 1,
					"fix_hint": "Set SE01 to 5.",
				}
			],
		)
		self.assertEqual(serialized["warnings"], [])
		self.assertIn("compliant=False", compliance_result_to_text(result))
