from types import SimpleNamespace
from unittest import TestCase

import frappe

from asn_module.asn_module.doctype.flow_step.flow_step import FlowStep


def _build_step(**overrides) -> SimpleNamespace:
	values = {
		"label": " ",
		"from_doctype": " ASN ",
		"to_doctype": " Purchase Receipt ",
		"execution_mode": "Mapping",
		"mapping_set": " MAP-1 ",
		"server_script": "",
		"generation_mode": "Hybrid",
		"scan_action_key": " create_pr ",
	}
	values.update(overrides)
	return SimpleNamespace(**values)


class TestFlowStepValidation(TestCase):
	def test_validate_normalizes_fields_and_defaults_label(self):
		step = _build_step()

		FlowStep.validate(step)

		self.assertEqual(step.from_doctype, "ASN")
		self.assertEqual(step.to_doctype, "Purchase Receipt")
		self.assertEqual(step.execution_mode, "Mapping")
		self.assertEqual(step.scan_action_key, "create_pr")
		self.assertEqual(step.generation_mode, "hybrid")
		self.assertEqual(step.label, "ASN -> Purchase Receipt")

	def test_validate_requires_from_and_to_doctype(self):
		step = _build_step(from_doctype="", to_doctype="")
		with self.assertRaises(frappe.ValidationError):
			FlowStep.validate(step)

	def test_validate_requires_mapping_set_for_mapping_mode(self):
		step = _build_step(execution_mode="Mapping", mapping_set=" ")
		with self.assertRaises(frappe.ValidationError):
			FlowStep.validate(step)

	def test_validate_requires_server_script_for_server_script_mode(self):
		step = _build_step(execution_mode="Server Script", mapping_set="", server_script=" ")
		with self.assertRaises(frappe.ValidationError):
			FlowStep.validate(step)

	def test_validate_rejects_invalid_generation_mode(self):
		step = _build_step(generation_mode="later")
		with self.assertRaises(frappe.ValidationError):
			FlowStep.validate(step)
