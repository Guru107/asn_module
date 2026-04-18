from dataclasses import dataclass
from typing import Any

from asn_module.edi_856.parser import ParsedEdi
from asn_module.edi_856.rules_4010 import CNT_SE02_ST02_MATCH_001, SEG_BSN_REQ_001


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
	rule_id: str
	severity: str
	message: str
	segment_tag: str
	segment_index: int
	element_index: int
	fix_hint: str


@dataclass(frozen=True, slots=True)
class ComplianceResult:
	is_compliant: bool
	errors: tuple[ComplianceFinding, ...]
	warnings: tuple[ComplianceFinding, ...]
	computed_metrics: dict[str, Any]


def validate_856_baseline(parsed: ParsedEdi) -> ComplianceResult:
	errors: list[ComplianceFinding] = []
	warnings: list[ComplianceFinding] = []

	segments = parsed.segments
	st_segment = next((segment for segment in segments if segment.tag == "ST"), None)
	bsn_segment = next((segment for segment in segments if segment.tag == "BSN"), None)
	se_segment = next((segment for segment in segments if segment.tag == "SE"), None)

	if bsn_segment is None:
		errors.append(
			ComplianceFinding(
				rule_id=SEG_BSN_REQ_001,
				severity="error",
				message="Missing required BSN segment.",
				segment_tag="BSN",
				segment_index=1 if st_segment is not None else -1,
				element_index=-1,
				fix_hint="Add a BSN segment after ST.",
			)
		)

	if st_segment is not None and se_segment is not None:
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
		"has_bsn": bsn_segment is not None,
	}

	return ComplianceResult(
		is_compliant=not errors,
		errors=tuple(errors),
		warnings=tuple(warnings),
		computed_metrics=computed_metrics,
	)
