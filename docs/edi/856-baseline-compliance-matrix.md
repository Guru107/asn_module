# X12 4010 Shipment Notice Baseline Compliance Matrix

## Scope
- Baseline: X12 4010 shipment notice transaction-set validation implemented in `asn_module/edi_856`.
- Claim standard: every mandatory baseline rule is codified with a stable rule ID and mapped to automated tests.

## Rule to Test Mapping

| Rule ID | Baseline constraint | Negative coverage (rule violation) | Positive coverage (no violation) |
|---|---|---|---|
| `SEG-ST-REQ-001` | ST segment is required | `test_missing_st_validates_in_place_without_outside_scope_noise` | `test_accepts_raw_edi_string_input` |
| `SEG-BSN-REQ-001` | BSN segment is required | `test_missing_segment_index_uses_nearest_required_neighbor` | `test_accepts_raw_edi_string_input` |
| `SEG-HL-REQ-001` | At least one HL segment is required | `test_missing_hl_and_ctt_produce_required_segment_errors` | `test_accepts_raw_edi_string_input` |
| `SEG-CTT-REQ-001` | CTT segment is required | `test_missing_hl_and_ctt_produce_required_segment_errors` | `test_accepts_raw_edi_string_input` |
| `SEG-SE-REQ-001` | SE segment is required | `test_missing_se_produces_required_segment_error` | `test_accepts_raw_edi_string_input` |
| `SEG-ST-CARD-001` | ST appears once in the selected transaction set | structural invariant via transaction-set scoping in `validate_856_baseline` | `test_selects_first_856_transaction_set_in_mixed_interchange` |
| `SEG-BSN-CARD-001` | BSN appears once | `test_duplicate_singletons_still_produce_cardinality_errors` | `test_accepts_raw_edi_string_input` |
| `SEG-CTT-CARD-001` | CTT appears once | `test_duplicate_singletons_still_produce_cardinality_errors` | `test_accepts_raw_edi_string_input` |
| `SEG-SE-CARD-001` | SE appears once | `test_duplicate_singletons_still_produce_cardinality_errors`, `test_trailing_se_outside_primary_scope_still_triggers_se_cardinality_error` | `test_accepts_raw_edi_string_input` |
| `SEG-OUTSIDE-SCOPE-001` | Business segments must remain inside selected ST..SE scope | `test_business_segment_after_se_is_non_compliant` | `test_envelope_tags_outside_scope_are_allowed` |
| `ORD-ST-BSN-001` | ST must precede BSN | structural invariant under ST..SE scope selection | `test_selects_first_856_transaction_set_in_mixed_interchange` |
| `ORD-BSN-HL-001` | BSN must precede HL | `test_ordering_violations_still_produce_order_errors` | `test_accepts_raw_edi_string_input` |
| `ORD-HL-CTT-001` | HL must precede CTT | `test_ctt_and_se_ordering_violations_still_produce_order_errors` | `test_accepts_raw_edi_string_input` |
| `ORD-CTT-SE-001` | CTT must precede SE | structural invariant under ST..SE scope selection | `test_selects_first_856_transaction_set_in_mixed_interchange` |
| `ELM-ST01-856-001` | ST01 must identify shipment notice transaction set | `test_non_856_transaction_fails_st01_rule` | `test_accepts_raw_edi_string_input` |
| `ELM-ST02-REQ-001` | ST02 control number is required | `test_st02_and_se02_are_required` | `test_accepts_raw_edi_string_input` |
| `ELM-SE02-REQ-001` | SE02 control number is required | `test_st02_and_se02_are_required` | `test_accepts_raw_edi_string_input` |
| `CNT-SE02-ST02-MATCH-001` | ST02 and SE02 control numbers must match | `test_se02_mismatch_pins_metadata_and_reporting` | `test_computed_metrics_include_hierarchy_and_control_indicators` |
| `CNT-SE01-SCOPE-COUNT-001` | SE01 must match actual scoped segment count | `test_se01_segment_count_mismatch_pins_metadata_and_reporting` | `test_computed_metrics_include_hierarchy_and_control_indicators` |
| `ELM-BSN01-REQ-001` | BSN01 is required | `test_bsn_required_elements_are_enforced` | `test_accepts_raw_edi_string_input` |
| `ELM-BSN02-REQ-001` | BSN02 is required | `test_bsn_required_elements_are_enforced` | `test_accepts_raw_edi_string_input` |
| `ELM-BSN03-REQ-001` | BSN03 is required | `test_bsn_required_elements_are_enforced` | `test_accepts_raw_edi_string_input` |
| `FMT-BSN03-DATE-001` | BSN03 must use `CCYYMMDD` | `test_bsn03_requires_ccyymmdd_format` | `test_accepts_raw_edi_string_input` |
| `HL-HL01-REQ-001` | HL01 is required | `test_hl01_must_be_non_empty_and_unique` | `test_accepts_raw_edi_string_input` |
| `HL-HL01-UNIQUE-001` | HL01 must be unique | `test_hl01_must_be_non_empty_and_unique` | `test_computed_metrics_include_hierarchy_and_control_indicators` |
| `HL-PARENT-REF-001` | HL02 must reference a prior HL01 when populated | `test_invalid_hl_parent_reference_fails_hierarchy_rule` | `test_computed_metrics_include_hierarchy_and_control_indicators` |
| `ELM-CTT01-NUMERIC-001` | CTT01 must be numeric | `test_ctt01_must_be_numeric` | `test_accepts_raw_edi_string_input` |
| `CNT-CTT01-HL-COUNT-001` | CTT01 must match derived HL quantity basis | `test_ctt01_compares_against_item_hl_count_when_present`, `test_ctt01_falls_back_to_total_hl_count_when_no_item_hls_exist` | `test_accepts_raw_edi_string_input` |

## Evidence Notes
- Full validator contract serialization is verified in `test_reporting_serializes_enriched_metrics_contract`.
- Mixed-interchange behavior and 856 scoping are verified in `test_selects_first_856_transaction_set_in_mixed_interchange` and `test_mixed_interchange_has_metrics_use_selected_856_scope`.
