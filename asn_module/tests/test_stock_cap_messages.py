from frappe.tests.utils import FrappeTestCase

from asn_module.stock_cap.messages import format_breaches
from asn_module.stock_cap.models import Breach

BREACH = Breach(
	branch="Mumbai",
	item_code="WIDGET",
	row_idxs=(1, 2),
	on_hand=60.0,
	in_transit=20.0,
	baseline=80.0,
	incoming=40.0,
	projected=120.0,
	cap=100.0,
)


class TestStockCapMessages(FrappeTestCase):
	def test_detailed_message_includes_stock_figures(self):
		message = format_breaches([BREACH], detailed=True)
		self.assertIn("WIDGET", message)
		self.assertIn("Mumbai", message)
		self.assertIn("120", message)
		self.assertIn("100", message)
		self.assertIn("60", message)

	def test_redacted_message_hides_stock_figures(self):
		message = format_breaches([BREACH], detailed=False)
		self.assertIn("WIDGET", message)
		self.assertNotIn("Mumbai", message)
		self.assertNotIn("120", message)
		self.assertNotIn("60", message)

	def test_redacted_message_reports_allowed_qty(self):
		self.assertEqual(BREACH.allowed_qty, 20.0)
		self.assertIn("20", format_breaches([BREACH], detailed=False))

	def test_empty_breach_list_produces_empty_message(self):
		self.assertEqual(format_breaches([], detailed=True), "")
