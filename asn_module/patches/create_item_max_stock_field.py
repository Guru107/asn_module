from asn_module.custom_fields.item import setup as setup_item_fields


def execute():
	"""Backfill Item.custom_max_stock on sites installed before the stock cap shipped.

	after_install only runs on fresh installs, so existing sites would otherwise need the
	field created by hand. create_custom_fields is idempotent, so re-running is harmless.
	"""
	setup_item_fields()
