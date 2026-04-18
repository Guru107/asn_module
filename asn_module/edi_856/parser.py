from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
	tag: str
	elements: list[str]
	index: int


@dataclass(frozen=True, slots=True)
class ParsedEdi:
	segments: list[Segment]


def parse_edi(
	text: str,
	segment_separator: str = "~",
	element_separator: str = "*",
) -> ParsedEdi:
	segments: list[Segment] = []

	for raw_segment in text.split(segment_separator):
		segment_text = raw_segment.strip("\r\n")
		if segment_text == "":
			continue

		parts = segment_text.split(element_separator)

		segments.append(
			Segment(
				tag=parts[0],
				elements=parts[1:],
				index=len(segments),
			)
		)

	return ParsedEdi(segments=segments)
