from unittest.mock import patch

from asn_module.setup_actions import (
	DEFAULT_STANDARD_FLOW_NAME,
	DEFAULT_STANDARD_MAPPING_SET_NAME,
	ensure_default_standard_handler_flow,
	get_canonical_actions,
	get_standard_handler_templates,
	register_actions,
	sync_qr_action_definitions,
)
from asn_module.tests.compat import UnitTestCase


class TestSetupActions(UnitTestCase):
	def test_get_standard_handler_templates_returns_capability_rows(self):
		templates = get_standard_handler_templates()
		self.assertTrue(templates)
		self.assertTrue(any(row.get("from_doctype") == "ASN" for row in templates))

	def test_get_canonical_actions_returns_compatibility_shape(self):
		actions = get_canonical_actions()
		self.assertTrue(actions)
		first = actions[0]
		self.assertIn("action_key", first)
		self.assertIn("handler_method", first)
		self.assertIn("source_doctype", first)

	def test_legacy_noops_are_safe(self):
		self.assertIsNone(sync_qr_action_definitions())
		self.assertIsNone(register_actions())

	@patch("asn_module.setup_actions.get_standard_handler_templates")
	@patch("asn_module.setup_actions.frappe.get_doc")
	@patch("asn_module.setup_actions.frappe.db.exists")
	def test_ensure_default_standard_handler_flow_creates_mapping_set_and_flow(
		self,
		mock_exists,
		mock_get_doc,
		mock_templates,
	):
		mock_templates.return_value = [
			{
				"key": "asn_to_purchase_receipt",
				"from_doctype": "ASN",
				"to_doctype": "Purchase Receipt",
				"handler": "asn_module.handlers.purchase_receipt.create_from_asn",
			},
			{
				"key": "mr_to_rfq",
				"from_doctype": "Material Request",
				"to_doctype": "Request for Quotation",
				"handler": "asn_module.barcode_process_flow.handlers.material_request_to_rfq",
			},
		]

		def _exists(doctype, name):
			if doctype == "Barcode Mapping Set" and name == DEFAULT_STANDARD_MAPPING_SET_NAME:
				return False
			if doctype == "Barcode Process Flow" and name == DEFAULT_STANDARD_FLOW_NAME:
				return False
			return False

		mock_exists.side_effect = _exists
		captured_docs = []

		class _FakeDoc:
			def __init__(self, payload):
				self.payload = payload
				self.name = payload.get("flow_name") or payload.get("mapping_set_name")

			def insert(self, ignore_permissions=False):
				self.ignore_permissions = ignore_permissions

		def _get_doc(payload):
			captured_docs.append(payload)
			return _FakeDoc(payload)

		mock_get_doc.side_effect = _get_doc

		result = ensure_default_standard_handler_flow()

		self.assertEqual(result, DEFAULT_STANDARD_FLOW_NAME)
		self.assertEqual(len(captured_docs), 2)
		mapping_payload, flow_payload = captured_docs
		self.assertEqual(mapping_payload.get("doctype"), "Barcode Mapping Set")
		self.assertEqual(mapping_payload.get("mapping_set_name"), DEFAULT_STANDARD_MAPPING_SET_NAME)
		self.assertEqual(flow_payload.get("doctype"), "Barcode Process Flow")
		self.assertEqual(flow_payload.get("flow_name"), DEFAULT_STANDARD_FLOW_NAME)
		self.assertEqual(len(flow_payload.get("steps") or []), 2)
		self.assertTrue(all(step.get("mapping_set") == DEFAULT_STANDARD_MAPPING_SET_NAME for step in flow_payload["steps"]))

	@patch("asn_module.setup_actions.frappe.get_doc")
	@patch("asn_module.setup_actions.frappe.db.exists")
	@patch("asn_module.setup_actions.get_standard_handler_templates")
	def test_ensure_default_standard_handler_flow_reconciles_existing_flow(
		self,
		mock_templates,
		mock_exists,
		mock_get_doc,
	):
		mock_templates.return_value = [
			{
				"key": "asn_to_purchase_receipt",
				"from_doctype": "ASN",
				"to_doctype": "Purchase Receipt",
				"handler": "asn_module.handlers.purchase_receipt.create_from_asn",
			}
		]

		def _exists(doctype, name):
			if doctype == "Barcode Mapping Set" and name == DEFAULT_STANDARD_MAPPING_SET_NAME:
				return True
			if doctype == "Barcode Process Flow" and name == DEFAULT_STANDARD_FLOW_NAME:
				return True
			return False

		mock_exists.side_effect = _exists
		flow_doc = type(
			"FlowDoc",
			(),
			{
				"is_active": 0,
				"description": "",
				"set": lambda self, fieldname, value: setattr(self, fieldname, value),
				"save": lambda self, ignore_permissions=False: setattr(self, "_saved", ignore_permissions),
			},
		)()
		mock_get_doc.return_value = flow_doc

		result = ensure_default_standard_handler_flow()

		self.assertEqual(result, DEFAULT_STANDARD_FLOW_NAME)
		mock_get_doc.assert_called_once_with("Barcode Process Flow", DEFAULT_STANDARD_FLOW_NAME)
		self.assertEqual(flow_doc.is_active, 1)
		self.assertTrue(bool(flow_doc.steps))
		self.assertTrue(flow_doc._saved)

	@patch("asn_module.setup_actions.frappe.get_doc")
	@patch("asn_module.setup_actions.frappe.db.exists")
	def test_ensure_default_standard_handler_flow_sets_rule_for_doc_conditions(
		self,
		mock_exists,
		mock_get_doc,
	):
		template = {
			"key": "mr_purchase_to_po",
			"from_doctype": "Material Request",
			"to_doctype": "Purchase Order",
			"doc_conditions": {"material_request_type": ["Purchase"]},
		}

		def _exists(doctype, name):
			if doctype == "Barcode Mapping Set" and name == DEFAULT_STANDARD_MAPPING_SET_NAME:
				return True
			if doctype == "Barcode Rule" and name == "System::Default::Rule::mr_purchase_to_po":
				return False
			return False

		mock_exists.side_effect = _exists
		captured = []

		class _Doc:
			def __init__(self, payload):
				self.payload = payload
				self.name = payload.get("rule_name") or payload.get("flow_name") or "DOC"

			def insert(self, ignore_permissions=False):
				self.ignore_permissions = ignore_permissions
				return self

		def _get_doc(payload):
			captured.append(payload)
			return _Doc(payload)

		mock_get_doc.side_effect = _get_doc

		with patch("asn_module.setup_actions.get_standard_handler_templates", return_value=[template]):
			ensure_default_standard_handler_flow()

		rule_docs = [row for row in captured if row.get("doctype") == "Barcode Rule"]
		self.assertEqual(len(rule_docs), 1)
		self.assertEqual(rule_docs[0].get("rule_name"), "System::Default::Rule::mr_purchase_to_po")
		self.assertEqual(rule_docs[0].get("field_path"), "material_request_type")
		self.assertEqual(rule_docs[0].get("operator"), "=")
		self.assertEqual(rule_docs[0].get("value"), "Purchase")
