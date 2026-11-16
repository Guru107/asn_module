from asn_module.stock_cap.messages import format_breaches
from asn_module.stock_cap.models import Breach
from asn_module.tests.compat import IntegrationTestCase

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


class TestStockCapMessages(IntegrationTestCase):
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
		self.assertIn("cannot take this quantity", message)
		self.assertIn("at most 20", message)
		self.assertNotIn("Stock Cap", message)

	def test_a_full_stock_cap_tells_the_supplier_they_cannot_declare_any_more(self):
		"""On hand already equals Maximum Stock. The supplier hears why, not the figures."""
		breach = Breach(
			branch="Nashik",
			item_code="FG02SHR",
			row_idxs=(1,),
			on_hand=500.0,
			in_transit=0.0,
			baseline=500.0,
			incoming=1.0,
			projected=501.0,
			cap=500.0,
			conversion_factor=1.0,
		)
		message = format_breaches([breach], detailed=False)
		self.assertIn("FG02SHR", message)
		self.assertIn("as much of this item as it can take", message)
		self.assertIn("cannot declare any more", message)
		self.assertNotIn("Stock Cap", message)
		self.assertNotIn("Nashik", message)
		self.assertNotIn("500", message)
		self.assertNotIn("0.0", message)

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
		self.assertNotIn("Stock Cap", message)
