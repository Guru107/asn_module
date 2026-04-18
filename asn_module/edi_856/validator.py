from dataclasses import dataclass

from asn_module.edi_856.parser import ParsedEdi
from asn_module.edi_856.rules_4010 import (
	CNT_SE02_ST02_MATCH_001,
	REQUIRED_SEGMENTS,
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
	return f"SEG-{tag}-REQ-001"


def _order_violation_rule_id() -> str:
	return "ORD-ST-FIRST-001"


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

	if st_segment is not None:
		for required_tag in REQUIRED_SEGMENTS:
			if required_tag == "ST":
				continue
			first_index = segment_by_tag.get(required_tag, [None])[0]
			if first_index is not None and first_index < st_segment.index:
				errors.append(
					ComplianceFinding(
						rule_id=_order_violation_rule_id(),
						severity="error",
						message=f"{required_tag} appears before ST.",
						segment_tag=required_tag,
						segment_index=first_index,
						element_index=None,
						fix_hint="Move ST before all other transaction-set segments.",
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
