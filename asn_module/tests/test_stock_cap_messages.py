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
		message = format_breaches([BREACH], detailed=False)
		self.assertIn("at most 20", message)
		self.assertNotIn("more", message)

	def test_empty_breach_list_produces_empty_message(self):
		self.assertEqual(format_breaches([], detailed=True), "")

	def test_redacted_message_uses_purchase_uom_when_lines_share_a_factor(self):
		breach = Breach(
			branch="Mumbai",
			item_code="WIDGET",
			row_idxs=(1,),
			on_hand=0.0,
			in_transit=0.0,
			baseline=0.0,
			incoming=36.0,
			projected=36.0,
			cap=24.0,
			conversion_factor=12.0,
		)
		message = format_breaches([breach], detailed=False)
		self.assertIn("at most 2", message)
		self.assertNotIn("24", message)
		self.assertNotIn("more", message)
