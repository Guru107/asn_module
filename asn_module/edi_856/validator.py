from dataclasses import dataclass
from itertools import pairwise

from asn_module.edi_856.parser import ParsedEdi
from asn_module.edi_856.rules_4010 import (
	CNT_SE01_SCOPE_COUNT_001,
	CNT_SE02_ST02_MATCH_001,
	ORD_BSN_HL_001,
	ORD_CTT_SE_001,
	ORD_HL_CTT_001,
	ORD_ST_BSN_001,
	REQUIRED_SEGMENTS,
	SEG_BSN_CARD_001,
	SEG_BSN_REQ_001,
	SEG_CTT_CARD_001,
	SEG_CTT_REQ_001,
	SEG_HL_REQ_001,
	SEG_SE_CARD_001,
	SEG_SE_REQ_001,
	SEG_ST_CARD_001,
	SEG_ST_REQ_001,
)


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
	rule_id: str
	severity: str
	message: str
	segment_tag: str | None
	segment_index: int | None
	element_index: int | None
	fix_hint: str | None


@dataclass(frozen=True, slots=True)
class ComplianceResult:
	is_compliant: bool
	errors: tuple[ComplianceFinding, ...]
	warnings: tuple[ComplianceFinding, ...]
	computed_metrics: dict[str, int]


def _missing_required_segment_rule_id(tag: str) -> str:
	return {
		"ST": SEG_ST_REQ_001,
		"BSN": SEG_BSN_REQ_001,
		"HL": SEG_HL_REQ_001,
		"CTT": SEG_CTT_REQ_001,
		"SE": SEG_SE_REQ_001,
	}.get(tag, f"SEG-{tag}-REQ-001")


def _sequence_rule_id(left_tag: str, right_tag: str) -> str:
	return {
		("ST", "BSN"): ORD_ST_BSN_001,
		("BSN", "HL"): ORD_BSN_HL_001,
		("HL", "CTT"): ORD_HL_CTT_001,
		("CTT", "SE"): ORD_CTT_SE_001,
	}.get((left_tag, right_tag), f"ORD-{left_tag}-{right_tag}-001")


def _singleton_cardinality_rule_id(tag: str) -> str:
	return {
		"ST": SEG_ST_CARD_001,
		"BSN": SEG_BSN_CARD_001,
		"CTT": SEG_CTT_CARD_001,
		"SE": SEG_SE_CARD_001,
	}.get(tag, f"SEG-{tag}-CARD-001")


def validate_856_baseline(parsed: ParsedEdi) -> ComplianceResult:
	errors: list[ComplianceFinding] = []
	warnings: list[ComplianceFinding] = []

	segments = parsed.segments
	segment_by_tag: dict[str, list[int]] = {}
	for segment in segments:
		segment_by_tag.setdefault(segment.tag, []).append(segment.index)

	st_segment = next((segment for segment in segments if segment.tag == "ST"), None)
	bsn_segment = next((segment for segment in segments if segment.tag == "BSN"), None)
	se_segment = next((segment for segment in segments if segment.tag == "SE"), None)

	for required_tag in REQUIRED_SEGMENTS:
		if required_tag not in segment_by_tag:
			reference_index: int | None = None
			if st_segment is not None and required_tag != "ST":
				reference_index = st_segment.index + 1

			errors.append(
				ComplianceFinding(
					rule_id=_missing_required_segment_rule_id(required_tag),
					severity="error",
					message=f"Missing required {required_tag} segment.",
					segment_tag=required_tag,
					segment_index=reference_index,
					element_index=None,
					fix_hint=(
						"Add a BSN segment after ST."
						if required_tag == "BSN"
						else f"Add a {required_tag} segment in the transaction set."
					),
				)
			)

	for singleton_tag in ("ST", "BSN", "CTT", "SE"):
		positions = segment_by_tag.get(singleton_tag, [])
		if len(positions) > 1:
			errors.append(
				ComplianceFinding(
					rule_id=_singleton_cardinality_rule_id(singleton_tag),
					severity="error",
					message=f"Duplicate {singleton_tag} segment.",
					segment_tag=singleton_tag,
					segment_index=positions[1],
					element_index=None,
					fix_hint=f"Keep only one {singleton_tag} segment.",
				)
			)

	if st_segment is not None:
		ordered_required_tags = ("ST", "BSN", "HL", "CTT", "SE")
		for left_tag, right_tag in pairwise(ordered_required_tags):
			left_index = segment_by_tag.get(left_tag, [None])[0]
			right_index = segment_by_tag.get(right_tag, [None])[0]
			if left_index is not None and right_index is not None and left_index > right_index:
				errors.append(
					ComplianceFinding(
						rule_id=_sequence_rule_id(left_tag, right_tag),
						severity="error",
						message=f"{left_tag} appears after {right_tag}.",
						segment_tag=right_tag,
						segment_index=right_index,
						element_index=None,
						fix_hint="Restore the required order: ST -> BSN -> HL -> CTT -> SE.",
					)
				)

	if st_segment is not None and se_segment is not None:
		st_index = st_segment.index
		se_index = se_segment.index
		if se_index > st_index:
			actual_segment_count = se_index - st_index + 1
			se01 = se_segment.elements[0] if len(se_segment.elements) > 0 else ""
			if se01 != str(actual_segment_count):
				errors.append(
				ComplianceFinding(
					rule_id=CNT_SE01_SCOPE_COUNT_001,
					severity="error",
					message=f"SE01 '{se01}' does not match count '{actual_segment_count}'.",
					segment_tag="SE",
					segment_index=se_index,
					element_index=1,
					fix_hint=f"Set SE01 to {actual_segment_count}.",
				)
			)

		st_control = st_segment.elements[1] if len(st_segment.elements) > 1 else ""
		se_control = se_segment.elements[1] if len(se_segment.elements) > 1 else ""

		if st_control != se_control:
			errors.append(
				ComplianceFinding(
					rule_id=CNT_SE02_ST02_MATCH_001,
					severity="error",
					message=f"SE02 '{se_control}' does not match ST02 '{st_control}'.",
					segment_tag="SE",
					segment_index=se_segment.index,
					element_index=1,
					fix_hint="Set SE02 to match ST02.",
				)
			)

	computed_metrics = {
		"segment_count": len(segments),
		"error_count": len(errors),
		"warning_count": len(warnings),
		"has_st": int(st_segment is not None),
		"has_bsn": int(bsn_segment is not None),
		"has_se": int(se_segment is not None),
	}

	return ComplianceResult(
		is_compliant=not errors,
		errors=tuple(errors),
		warnings=tuple(warnings),
		computed_metrics=computed_metrics,
	)
