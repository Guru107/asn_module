from types import SimpleNamespace
from unittest.mock import patch

from asn_module.barcode_process_flow import submit_hooks
from asn_module.tests.compat import UnitTestCase


class TestSubmitHooks(UnitTestCase):
	def test_on_any_submit_generates_codes_for_all_eligible_steps(self):
		doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-1")
		with (
			patch(
				"asn_module.barcode_process_flow.submit_hooks.runtime.generate_codes_for_source_doc",
				return_value=[],
			) as generate_mock,
		):
			submit_hooks.on_any_submit(doc, "on_submit")
		generate_mock.assert_called_once_with(source_doc=doc, conditioned_only=False)

	def test_on_any_submit_skips_blank_doctype(self):
		doc = SimpleNamespace(doctype="", name="DOC-1")
		with patch(
			"asn_module.barcode_process_flow.submit_hooks.runtime.generate_codes_for_source_doc",
		) as generate_mock:
			submit_hooks.on_any_submit(doc, "on_submit")
		generate_mock.assert_not_called()

	def test_on_any_submit_logs_and_does_not_raise(self):
		doc = SimpleNamespace(doctype="Purchase Receipt", name="PR-1")
		with (
			patch(
				"asn_module.barcode_process_flow.submit_hooks.runtime.generate_codes_for_source_doc",
				side_effect=RuntimeError("boom"),
			),
			patch("asn_module.barcode_process_flow.submit_hooks.frappe.log_error") as log_error,
		):
			submit_hooks.on_any_submit(doc, "on_submit")
		log_error.assert_called_once()
