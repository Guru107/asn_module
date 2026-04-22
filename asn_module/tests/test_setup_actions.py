from frappe.tests import UnitTestCase

from asn_module.setup_actions import (
	get_canonical_actions,
	get_standard_handler_templates,
	register_actions,
	sync_qr_action_definitions,
)


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
