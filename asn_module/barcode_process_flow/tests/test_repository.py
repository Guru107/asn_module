from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow import repository
from asn_module.tests.compat import UnitTestCase


class TestRepository(UnitTestCase):
	def test_get_rule_paths(self):
		self.assertIsNone(repository.get_rule(""))
		with patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=False):
			self.assertIsNone(repository.get_rule("RULE-1"))

		rule = SimpleNamespace(is_active=0)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=rule),
		):
			self.assertIsNone(repository.get_rule("RULE-1"))

		rule_active = SimpleNamespace(is_active=1)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=rule_active),
		):
			self.assertIs(repository.get_rule("RULE-1"), rule_active)

	def test_get_mapping_set_paths(self):
		self.assertIsNone(repository.get_mapping_set(""))
		with patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=False):
			self.assertIsNone(repository.get_mapping_set("MAP-1"))

		mapping_set = SimpleNamespace(is_active=0)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=mapping_set),
		):
			self.assertIsNone(repository.get_mapping_set("MAP-1"))

		mapping_set_active = SimpleNamespace(is_active=1)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=mapping_set_active
			),
		):
			self.assertIs(repository.get_mapping_set("MAP-1"), mapping_set_active)

	def test_flow_step_returns_rows_with_from_and_to_doctype(self):
		source = SimpleNamespace(doctype="ASN", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=["FLOW-1"]),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
		):
			rows = repository.get_active_steps_for_source(source)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].from_doctype, "ASN")
		self.assertEqual(rows[0].to_doctype, "Purchase Receipt")

	def test_asn_resolves_company_from_linked_purchase_order_for_flow_scope(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-0001", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="TCPL",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)

		def _mock_get_all(doctype, *args, **kwargs):
			if doctype == "ASN Item":
				return [{"purchase_order": "PO-0001"}]
			if doctype == "Barcode Process Flow":
				return ["FLOW-1"]
			return []

		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", side_effect=_mock_get_all),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.db.get_value",
				return_value="TCPL",
			),
		):
			rows = repository.get_active_steps_for_source(source)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].from_doctype, "ASN")
		self.assertEqual(rows[0].to_doctype, "Purchase Receipt")

	def test_asn_company_scope_mismatch_skips_flow(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-0001", supplier="", company="")
		flow = SimpleNamespace(
			name="FLOW-1",
			flow_name="Inbound",
			company="TCPL",
			steps=[
				SimpleNamespace(
					name="STEP-1", is_active=1, from_doctype="ASN", to_doctype="Purchase Receipt", label=""
				)
			],
		)

		def _mock_get_all(doctype, *args, **kwargs):
			if doctype == "ASN Item":
				return [{"purchase_order": "PO-0001"}]
			if doctype == "Barcode Process Flow":
				return ["FLOW-1"]
			return []

		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", side_effect=_mock_get_all),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.db.get_value",
				return_value="OTHER-COMPANY",
			),
		):
			rows = repository.get_active_steps_for_source(source)

		self.assertEqual(rows, [])

	def test_get_active_steps_filters_by_action_key_and_defaults_scan_key(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-1", company="")
		flow = SimpleNamespace(
			name="FLOW",
			flow_name="Inbound",
			company="",
			steps=[
				SimpleNamespace(
					name="STEP-1",
					is_active=1,
					from_doctype="ASN",
					to_doctype="Purchase Receipt",
					label="",
					scan_action_key="",
					execution_mode="Mapping",
					mapping_set="MAP-1",
					server_script="",
					condition="",
					priority=100,
					generate_next_barcode=1,
					generation_mode="hybrid",
				),
				SimpleNamespace(
					name="STEP-2",
					is_active=1,
					from_doctype="ASN",
					to_doctype="Subcontracting Receipt",
					label="",
					scan_action_key="asn_to_subcontracting_receipt",
					execution_mode="Mapping",
					mapping_set="MAP-1",
					server_script="",
					condition="",
					priority=50,
					generate_next_barcode=1,
					generation_mode="runtime",
				),
			],
		)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=["FLOW"]),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository._build_context", return_value={"company": None}
			),
		):
			all_rows = repository.get_active_steps_for_source(source)
			filtered_rows = repository.get_active_steps_for_source(source, action_key="STEP-1")
			filtered_rows_padded = repository.get_active_steps_for_source(source, action_key=" STEP-1 ")
			filtered_by_scan_key = repository.get_active_steps_for_source(
				source, action_key="asn_to_subcontracting_receipt"
			)

		self.assertEqual(len(all_rows), 2)
		self.assertEqual(all_rows[0].scan_action_key, "STEP-1")
		self.assertEqual(len(filtered_rows), 1)
		self.assertEqual(filtered_rows[0].step_name, "STEP-1")
		self.assertEqual(len(filtered_rows_padded), 1)
		self.assertEqual(filtered_rows_padded[0].step_name, "STEP-1")
		self.assertEqual(len(filtered_by_scan_key), 1)
		self.assertEqual(filtered_by_scan_key[0].step_name, "STEP-2")

	def test_get_active_steps_returns_empty_when_source_doctype_missing(self):
		self.assertEqual(repository.get_active_steps_for_source(SimpleNamespace(doctype="")), [])

	def test_get_active_steps_skips_inactive_step_rows(self):
		source = SimpleNamespace(doctype="ASN", name="ASN-1", company="")
		flow = SimpleNamespace(
			name="FLOW",
			flow_name="Inbound",
			company="",
			steps=[
				SimpleNamespace(
					name="STEP-INACTIVE", is_active=0, from_doctype="ASN", to_doctype="Purchase Receipt"
				),
			],
		)
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=["FLOW"]),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=flow),
			patch(
				"asn_module.barcode_process_flow.repository._build_context", return_value={"company": None}
			),
		):
			self.assertEqual(repository.get_active_steps_for_source(source), [])

	def test_get_step_by_name_paths(self):
		self.assertIsNone(repository.get_step_by_name(""))
		with patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=False):
			self.assertIsNone(repository.get_step_by_name("STEP-1"))

		step = SimpleNamespace(name="STEP-1", is_active=1, parent="FLOW-1")
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=step),
			patch("asn_module.barcode_process_flow.repository.frappe.db.get_value", return_value=1),
		):
			self.assertIs(repository.get_step_by_name("STEP-1"), step)

		inactive_step = SimpleNamespace(name="STEP-2", is_active=0, parent="FLOW-1")
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=inactive_step),
		):
			self.assertIsNone(repository.get_step_by_name("STEP-2"))

		orphan_step = SimpleNamespace(name="STEP-3", is_active=1, parent="")
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch("asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=orphan_step),
		):
			self.assertIsNone(repository.get_step_by_name("STEP-3"))

		inactive_flow_step = SimpleNamespace(name="STEP-4", is_active=1, parent="FLOW-2")
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.get_doc", return_value=inactive_flow_step
			),
			patch("asn_module.barcode_process_flow.repository.frappe.db.get_value", return_value=0),
		):
			self.assertIsNone(repository.get_step_by_name("STEP-4"))

		legacy_step_without_is_active = SimpleNamespace(name="STEP-5", parent="FLOW-1")
		with (
			patch("asn_module.barcode_process_flow.repository.frappe.db.exists", return_value=True),
			patch(
				"asn_module.barcode_process_flow.repository.frappe.get_doc",
				return_value=legacy_step_without_is_active,
			),
			patch("asn_module.barcode_process_flow.repository.frappe.db.get_value", return_value=1),
		):
			self.assertIs(repository.get_step_by_name("STEP-5"), legacy_step_without_is_active)

	def test_build_context_and_flow_match_helpers(self):
		self.assertEqual(
			repository._build_context(SimpleNamespace(doctype="Purchase Receipt", company="TCPL")),
			{"company": "TCPL"},
		)
		self.assertEqual(
			repository._build_context(SimpleNamespace(doctype="Material Request", company="")),
			{"company": None},
		)
		self.assertTrue(repository._flow_matches_context(SimpleNamespace(company=""), {"company": None}))
		self.assertFalse(
			repository._flow_matches_context(SimpleNamespace(company="TCPL"), {"company": "OTHER"})
		)

	def test_resolve_company_returns_none_when_asn_has_no_linked_po(self):
		with patch(
			"asn_module.barcode_process_flow.repository._first_linked_purchase_order",
			return_value=None,
		):
			self.assertIsNone(
				repository._resolve_company(SimpleNamespace(doctype="ASN", name="ASN-1", company=""))
			)

	def test_first_linked_purchase_order_returns_none_when_no_rows(self):
		with patch("asn_module.barcode_process_flow.repository.frappe.get_all", return_value=[]):
			self.assertIsNone(
				repository._first_linked_purchase_order(
					SimpleNamespace(items=[]),
					"ASN-1",
				)
			)
