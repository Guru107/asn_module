from dataclasses import dataclass
from itertools import pairwise

from asn_module.edi_856.parser import ParsedEdi, Segment, parse_edi
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
	ORD_CTT_SE_001,
	ORD_HL_CTT_001,
	ORD_ST_BSN_001,
	REQUIRED_SEGMENTS,
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


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
	rule_id: str
	severity: str
	message: str
	segment_tag: str | None
	segment_index: int | None
	element_index: int | None
	fix_hint: str | None


@dataclass(slots=True)
class ComplianceResult:
	is_compliant: bool
	errors: list[ComplianceFinding]
	warnings: list[ComplianceFinding]
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


def _expected_missing_segment_index(tag: str, segment_by_tag: dict[str, list[int]]) -> int:
	ordered_required_tags = ("ST", "BSN", "HL", "CTT", "SE")
	tag_position = ordered_required_tags.index(tag)

	for left_tag in reversed(ordered_required_tags[:tag_position]):
		left_positions = segment_by_tag.get(left_tag)
		if left_positions:
			return left_positions[0] + 1

	for right_tag in ordered_required_tags[tag_position + 1 :]:
		right_positions = segment_by_tag.get(right_tag)
		if right_positions:
			return right_positions[0]

	return 0


def _segment_element(segment: Segment, element_index: int) -> str:
	zero_based_index = element_index - 1
	if zero_based_index < 0 or zero_based_index >= len(segment.elements):
		return ""
	return segment.elements[zero_based_index]


def _selected_transaction_segments(
	segments: list[Segment],
) -> tuple[int | None, int | None, Segment | None, Segment | None]:
	transaction_ranges = _transaction_ranges(segments)
	if not transaction_ranges:
		return None, None, None, None

	selected_range = next(
		(transaction_range for transaction_range in transaction_ranges if _segment_element(transaction_range[2], 1) == "856"),
		transaction_ranges[0],
	)
	scope_start, scope_end, selected_st_segment, selected_se_segment = selected_range
	return scope_start, scope_end, selected_st_segment, selected_se_segment


def _transaction_ranges(
	segments: list[Segment],
) -> list[tuple[int, int, Segment, Segment | None]]:
	transaction_ranges: list[tuple[int, int, Segment, Segment | None]] = []
	open_st_segment: Segment | None = None

	for segment in segments:
		if segment.tag == "ST":
			if open_st_segment is not None:
				transaction_ranges.append((open_st_segment.index, segment.index - 1, open_st_segment, None))
			open_st_segment = segment
			continue

		if segment.tag == "SE" and open_st_segment is not None:
			transaction_ranges.append((open_st_segment.index, segment.index, open_st_segment, segment))
			open_st_segment = None

	if open_st_segment is not None:
		transaction_ranges.append((open_st_segment.index, segments[-1].index, open_st_segment, None))

	return transaction_ranges


def _indexes_in_range(start: int, end: int) -> set[int]:
	return set(range(start, end + 1))


def _is_envelope_tag(tag: str) -> bool:
	return tag in {"ISA", "GS", "GE", "IEA"}


def _append_error(
	errors: list[ComplianceFinding],
	*,
	rule_id: str,
	message: str,
	segment_tag: str | None,
	segment_index: int | None,
	element_index: int | None = None,
	fix_hint: str | None = None,
) -> None:
	errors.append(
		ComplianceFinding(
			rule_id=rule_id,
			severity="error",
			message=message,
			segment_tag=segment_tag,
			segment_index=segment_index,
			element_index=element_index,
			fix_hint=fix_hint,
		)
	)


def _validate_hl_hierarchy(
	scope_segments: list[Segment], errors: list[ComplianceFinding]
) -> tuple[int, int, int]:
	hl_segments = [segment for segment in scope_segments if segment.tag == "HL"]
	seen_hl_ids: set[str] = set()
	hl_depths: dict[str, int] = {}
	max_hl_depth = 0
	item_hl_count = 0

	for segment in hl_segments:
		hl01 = _segment_element(segment, 1)
		hl02 = _segment_element(segment, 2)
		hl03 = _segment_element(segment, 3)

		if hl03 == "I":
			item_hl_count += 1

		if hl01 == "":
			_append_error(
				errors,
				rule_id=HL_HL01_REQ_001,
				message="HL01 is required.",
				segment_tag="HL",
				segment_index=segment.index,
				element_index=1,
				fix_hint="Populate HL01 with a non-empty hierarchical ID.",
			)
			continue

		if hl01 in seen_hl_ids:
			_append_error(
				errors,
				rule_id=HL_HL01_UNIQUE_001,
				message=f"HL01 '{hl01}' must be unique.",
				segment_tag="HL",
				segment_index=segment.index,
				element_index=1,
				fix_hint="Assign a unique HL01 value to each HL segment.",
			)
			continue

		depth = 1
		if hl02:
			if hl02 not in seen_hl_ids:
				_append_error(
					errors,
					rule_id=HL_PARENT_REF_001,
					message=f"HL02 '{hl02}' does not reference an earlier HL01.",
					segment_tag="HL",
					segment_index=segment.index,
					element_index=2,
					fix_hint="Point HL02 to an existing earlier HL01, or leave it blank for the root HL.",
				)
			else:
				depth = hl_depths[hl02] + 1

		seen_hl_ids.add(hl01)
		hl_depths[hl01] = depth
		max_hl_depth = max(max_hl_depth, depth)

	return len(hl_segments), item_hl_count, max_hl_depth


def validate_856_baseline(parsed: ParsedEdi | str) -> ComplianceResult:
	errors: list[ComplianceFinding] = []
	warnings: list[ComplianceFinding] = []

	if isinstance(parsed, str):
		parsed = parse_edi(parsed)

	segments = parsed.segments
	transaction_ranges = _transaction_ranges(list(segments))
	scope_start, scope_end, st_segment, se_segment = _selected_transaction_segments(list(segments))

	if scope_start is None:
		scope_segments = list(segments)
		selected_scope_indexes: set[int] = {segment.index for segment in segments}
		other_transaction_indexes: set[int] = set()
	else:
		scope_segments = [segment for segment in segments if scope_start <= segment.index <= scope_end]
		selected_scope_indexes = _indexes_in_range(scope_start, scope_end)
		other_transaction_indexes = set()
		for start, end, range_st_segment, _ in transaction_ranges:
			if range_st_segment.index == st_segment.index:
				continue
			other_transaction_indexes.update(_indexes_in_range(start, end))

	segment_by_tag: dict[str, list[int]] = {}
	for segment in scope_segments:
		segment_by_tag.setdefault(segment.tag, []).append(segment.index)

	bsn_segment = next((segment for segment in scope_segments if segment.tag == "BSN"), None)
	ctt_segment = next((segment for segment in scope_segments if segment.tag == "CTT"), None)

	if scope_start is not None:
		outside_scope_segments = [
			segment
			for segment in segments
			if (
				segment.index not in selected_scope_indexes
				and segment.index not in other_transaction_indexes
				and not _is_envelope_tag(segment.tag)
			)
		]
	else:
		outside_scope_segments = []

	for segment in outside_scope_segments:
		_append_error(
			errors,
			rule_id=SEG_OUTSIDE_SCOPE_001,
			message=f"{segment.tag or 'segment'} is outside the transaction scope.",
			segment_tag=segment.tag or None,
			segment_index=segment.index,
			fix_hint="Move business segments inside the selected ST..SE transaction set.",
		)

	for required_tag in REQUIRED_SEGMENTS:
		if required_tag not in segment_by_tag:
			_append_error(
				errors,
				rule_id=_missing_required_segment_rule_id(required_tag),
				message=f"Missing required {required_tag} segment.",
				segment_tag=required_tag,
				segment_index=_expected_missing_segment_index(required_tag, segment_by_tag),
				fix_hint=(
					"Add a BSN segment after ST."
					if required_tag == "BSN"
					else f"Add a {required_tag} segment in the transaction set."
				),
			)

	full_segment_by_tag: dict[str, list[int]] = {}
	for segment in segments:
		if segment.index in other_transaction_indexes:
			continue
		full_segment_by_tag.setdefault(segment.tag, []).append(segment.index)

	for singleton_tag in ("ST", "BSN", "CTT", "SE"):
		positions = full_segment_by_tag.get(singleton_tag, [])
		if len(positions) > 1:
			_append_error(
				errors,
				rule_id=_singleton_cardinality_rule_id(singleton_tag),
				message=f"Duplicate {singleton_tag} segment.",
				segment_tag=singleton_tag,
				segment_index=positions[1],
				fix_hint=f"Keep only one {singleton_tag} segment.",
			)

	ordered_required_tags = ("ST", "BSN", "HL", "CTT", "SE")
	for left_tag, right_tag in pairwise(ordered_required_tags):
		left_index = segment_by_tag.get(left_tag, [None])[0]
		right_index = segment_by_tag.get(right_tag, [None])[0]
		if left_index is not None and right_index is not None and left_index > right_index:
			_append_error(
				errors,
				rule_id=_sequence_rule_id(left_tag, right_tag),
				message=f"{left_tag} appears after {right_tag}.",
				segment_tag=right_tag,
				segment_index=right_index,
				fix_hint="Restore the required order: ST -> BSN -> HL -> CTT -> SE.",
			)

	if st_segment is not None:
		st01 = _segment_element(st_segment, 1)
		st02 = _segment_element(st_segment, 2)
		if st01 != "856":
			_append_error(
				errors,
				rule_id=ELM_ST01_856_001,
				message=f"ST01 '{st01}' must be '856'.",
				segment_tag="ST",
				segment_index=st_segment.index,
				element_index=1,
				fix_hint="Set ST01 to 856 for the ASN transaction set.",
			)
		if st02 == "":
			_append_error(
				errors,
				rule_id=ELM_ST02_REQ_001,
				message="ST02 is required.",
				segment_tag="ST",
				segment_index=st_segment.index,
				element_index=2,
				fix_hint="Populate ST02 with the transaction set control number.",
			)

	if bsn_segment is not None:
		for element_index, rule_id in (
			(1, ELM_BSN01_REQ_001),
			(2, ELM_BSN02_REQ_001),
			(3, ELM_BSN03_REQ_001),
		):
			if _segment_element(bsn_segment, element_index) == "":
				_append_error(
					errors,
					rule_id=rule_id,
					message=f"BSN{element_index:02d} is required.",
					segment_tag="BSN",
					segment_index=bsn_segment.index,
					element_index=element_index,
					fix_hint=f"Populate BSN{element_index:02d}.",
				)

		bsn03 = _segment_element(bsn_segment, 3)
		if bsn03 != "" and (len(bsn03) != 8 or not bsn03.isdigit()):
			_append_error(
				errors,
				rule_id=FMT_BSN03_DATE_001,
				message=f"BSN03 '{bsn03}' must use CCYYMMDD format.",
				segment_tag="BSN",
				segment_index=bsn_segment.index,
				element_index=3,
				fix_hint="Set BSN03 to an 8-digit CCYYMMDD date.",
			)

	hl_count, item_hl_count, max_hl_depth = _validate_hl_hierarchy(scope_segments, errors)

	if ctt_segment is not None:
		ctt01 = _segment_element(ctt_segment, 1)
		if not ctt01.isdigit():
			_append_error(
				errors,
				rule_id=ELM_CTT01_NUMERIC_001,
				message=f"CTT01 '{ctt01}' must be numeric.",
				segment_tag="CTT",
				segment_index=ctt_segment.index,
				element_index=1,
				fix_hint="Set CTT01 to a numeric HL count.",
			)
		else:
			expected_ctt_count = item_hl_count if item_hl_count > 0 else hl_count
			count_basis = "item-level HL count" if item_hl_count > 0 else "total HL count"
			if int(ctt01) != expected_ctt_count:
				_append_error(
					errors,
					rule_id=CNT_CTT01_HL_COUNT_001,
					message=f"CTT01 '{ctt01}' does not match {count_basis} '{expected_ctt_count}'.",
					segment_tag="CTT",
					segment_index=ctt_segment.index,
					element_index=1,
					fix_hint=(
						f"Set CTT01 to {expected_ctt_count}; baseline validation uses the {count_basis}."
					),
				)

	st_control = _segment_element(st_segment, 2) if st_segment is not None else ""
	se_control = _segment_element(se_segment, 2) if se_segment is not None else ""
	if st_segment is not None and se_segment is not None:
		st_index = st_segment.index
		se_index = se_segment.index
		if se_index > st_index:
			actual_segment_count = se_index - st_index + 1
			se01 = _segment_element(se_segment, 1)
			if se01 != str(actual_segment_count):
				_append_error(
					errors,
					rule_id=CNT_SE01_SCOPE_COUNT_001,
					message=f"SE01 '{se01}' does not match count '{actual_segment_count}'.",
					segment_tag="SE",
					segment_index=se_index,
					element_index=1,
					fix_hint=f"Set SE01 to {actual_segment_count}.",
				)

		if se_control == "":
			_append_error(
				errors,
				rule_id=ELM_SE02_REQ_001,
				message="SE02 is required.",
				segment_tag="SE",
				segment_index=se_segment.index,
				element_index=2,
				fix_hint="Populate SE02 with the transaction set control number.",
			)

		if st_control != "" and se_control != "" and st_control != se_control:
			_append_error(
				errors,
				rule_id=CNT_SE02_ST02_MATCH_001,
				message=f"SE02 '{se_control}' does not match ST02 '{st_control}'.",
				segment_tag="SE",
				segment_index=se_segment.index,
				element_index=2,
				fix_hint="Set SE02 to match ST02.",
			)

	computed_metrics = {
		"segment_count": len(segments),
		"error_count": len(errors),
		"warning_count": len(warnings),
		"has_st": int(any(segment.tag == "ST" for segment in segments)),
		"has_bsn": int(any(segment.tag == "BSN" for segment in segments)),
		"has_se": int(any(segment.tag == "SE" for segment in segments)),
		"hl_count": hl_count,
		"item_hl_count": item_hl_count,
		"max_hl_depth": max_hl_depth,
		"has_st_control": int(st_control != ""),
		"has_se_control": int(se_control != ""),
		"st_se_control_match": int(st_control != "" and st_control == se_control),
	}

	return ComplianceResult(
		is_compliant=not errors,
		errors=errors,
		warnings=warnings,
		computed_metrics=computed_metrics,
	)
