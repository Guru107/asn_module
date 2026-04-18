from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
	tag: str
	elements: tuple[str, ...]
	index: int


@dataclass(frozen=True, slots=True)
class ParsedEdi:
	segments: tuple[Segment, ...]


def parse_edi(
	text: str,
	segment_separator: str = "~",
	element_separator: str = "*",
) -> ParsedEdi:
	segments: list[Segment] = []

	for raw_segment in text.split(segment_separator):
		segment_text = raw_segment.strip("\r\n")
		if segment_text.strip() == "":
			continue

		parts = segment_text.split(element_separator)

		segments.append(
			Segment(
				tag=parts[0].strip(),
				elements=tuple(parts[1:]),
				index=len(segments),
			)
		)

	return ParsedEdi(segments=tuple(segments))
