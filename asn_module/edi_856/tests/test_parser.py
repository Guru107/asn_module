from pathlib import Path
from unittest import TestCase

from asn_module.edi_856.parser import ParsedEdi, Segment, parse_edi

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestParseEdi(TestCase):
	def test_uses_default_separators(self):
		parsed = parse_edi("ST*856*0001~BSN*00*12345  ~HL*1**S~CTT*1~SE*5*0001~")

		self.assertIsInstance(parsed, ParsedEdi)
		self.assertIsInstance(parsed.segments, tuple)
		self.assertEqual(
			parsed.segments,
			(
				Segment(tag="ST", elements=("856", "0001"), index=0),
				Segment(tag="BSN", elements=("00", "12345  "), index=1),
				Segment(tag="HL", elements=("1", "", "S"), index=2),
				Segment(tag="CTT", elements=("1",), index=3),
				Segment(tag="SE", elements=("5", "0001"), index=4),
			),
		)

	def test_ignores_empty_segments_and_whitespace(self):
		parsed = parse_edi("ST*856*0001~   ~BSN*00*12345~")

		self.assertEqual(
			parsed.segments,
			(
				Segment(tag="ST", elements=("856", "0001"), index=0),
				Segment(tag="BSN", elements=("00", "12345"), index=1),
			),
		)

	def test_normalizes_tag_whitespace(self):
		parsed = parse_edi("ST*856*0001~ ISA*00*12345~")

		self.assertEqual(
			parsed.segments,
			(
				Segment(tag="ST", elements=("856", "0001"), index=0),
				Segment(tag="ISA", elements=("00", "12345"), index=1),
			),
		)

	def test_keeps_malformed_segment_with_empty_tag(self):
		parsed = parse_edi("ST*856*0001~*BROKEN*SEG~BSN*00*12345~")

		self.assertEqual(
			parsed.segments,
			(
				Segment(tag="ST", elements=("856", "0001"), index=0),
				Segment(tag="", elements=("BROKEN", "SEG"), index=1),
				Segment(tag="BSN", elements=("00", "12345"), index=2),
			),
		)

	def test_supports_separator_overrides(self):
		parsed = parse_edi("ST^856^0001|BSN^00^12345|", segment_separator="|", element_separator="^")

		self.assertEqual(
			parsed.segments,
			(
				Segment(tag="ST", elements=("856", "0001"), index=0),
				Segment(tag="BSN", elements=("00", "12345"), index=1),
			),
		)

	def test_parses_fixture_sample(self):
		fixture_path = FIXTURES_DIR / "valid_856_minimal.txt"
		parsed = parse_edi(fixture_path.read_text())

		self.assertEqual([segment.tag for segment in parsed.segments], ["ST", "BSN", "HL", "CTT", "SE"])
		self.assertEqual(parsed.segments[0], Segment(tag="ST", elements=("856", "0001"), index=0))
