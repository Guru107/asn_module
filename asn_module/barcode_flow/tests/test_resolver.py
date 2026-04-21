from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from asn_module.barcode_flow.errors import AmbiguousFlowScopeError, NoMatchingFlowError
from asn_module.barcode_flow.resolver import resolve_flow


class TestBarcodeFlowResolver(TestCase):
	def _new_scope(
		self,
		*,
		scope_key: str,
		priority: int = 0,
		is_default: int = 0,
		source_doctype: str | None = "ASN",
		company: str | None = None,
		warehouse: str | None = None,
		supplier_type: str | None = None,
	):
		return SimpleNamespace(
			scope_key=scope_key,
			priority=priority,
			is_default=is_default,
			source_doctype=source_doctype,
			company=company,
			warehouse=warehouse,
			supplier_type=supplier_type,
			is_active=1,
		)

	def _new_flow(self, *, name: str, scopes: list[SimpleNamespace]):
		return SimpleNamespace(
			name=name,
			is_active=1,
			scopes=scopes,
		)

	def test_prefers_more_specific_scope_match(self):
		context = {"source_doctype": "ASN", "company": "COMP-1", "warehouse": "WH-1"}
		flows = [
			self._new_flow(
				name="FLOW-COMPANY",
				scopes=[self._new_scope(scope_key="company-only", company="COMP-1")],
			),
			self._new_flow(
				name="FLOW-COMPANY-WH",
				scopes=[
					self._new_scope(
						scope_key="company-warehouse",
						company="COMP-1",
						warehouse="WH-1",
					)
				],
			),
		]

		with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
			resolved = resolve_flow(context)

		self.assertEqual(resolved.name, "FLOW-COMPANY-WH")

	def test_uses_priority_when_specificity_ties(self):
		flows = [
			self._new_flow(
				name="FLOW-LOW-PRIORITY",
				scopes=[self._new_scope(scope_key="low-priority", company="COMP-2", priority=10)],
			),
			self._new_flow(
				name="FLOW-HIGH-PRIORITY",
				scopes=[self._new_scope(scope_key="high-priority", company="COMP-2", priority=100)],
			),
		]

		with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
			resolved = resolve_flow({"source_doctype": "ASN", "company": "COMP-2"})

		self.assertEqual(resolved.name, "FLOW-HIGH-PRIORITY")

	def test_raises_ambiguity_error_when_winners_remain_tied(self):
		flows = [
			self._new_flow(
				name="FLOW-AMBIGUOUS-A",
				scopes=[self._new_scope(scope_key="scope-a", company="COMP-3", priority=50)],
			),
			self._new_flow(
				name="FLOW-AMBIGUOUS-B",
				scopes=[self._new_scope(scope_key="scope-b", company="COMP-3", priority=50)],
			),
		]

		with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
			with self.assertRaises(AmbiguousFlowScopeError):
				resolve_flow({"source_doctype": "ASN", "company": "COMP-3"})

	def test_raises_no_match_error_when_no_scope_matches(self):
		flows = [
			self._new_flow(
				name="FLOW-NON-MATCHING",
				scopes=[self._new_scope(scope_key="scope-unknown", company="COMP-X")],
			)
		]

		with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
			with self.assertRaises(NoMatchingFlowError):
				resolve_flow({"source_doctype": "ASN", "company": "COMP-Y"})

	def test_mismatched_source_doctype_does_not_match_scope(self):
		flows = [
			self._new_flow(
				name="FLOW-ASN",
				scopes=[
					self._new_scope(
						scope_key="asn-flow",
						source_doctype="ASN",
						company="COMP-4",
					)
				],
			)
		]

		with patch("asn_module.barcode_flow.resolver._get_active_flow_definitions", return_value=flows):
			with self.assertRaises(NoMatchingFlowError):
				resolve_flow({"source_doctype": "Purchase Receipt", "company": "COMP-4"})
