import math

import frappe
from frappe.model.meta import get_field_precision
from frappe.utils import flt


def system_float_precision() -> int:
	"""Precision Frappe applies to a Float field that does not set its own.

	Same path as ``Document.precision``: System Settings ``float_precision``, otherwise 3.
	"""
	return get_field_precision(frappe._dict(fieldtype="Float"))


def flt_qty(value) -> float:
	"""Round a quantity the way Frappe stores a Float field."""
	return flt(value, system_float_precision())


def floor_qty(value) -> float:
	"""Largest Float-precision value that is not above ``value``.

	``flt`` can round a headroom figure up, and the same precision then refuses it.
	The number of decimal places still comes from System Settings.
	"""
	scale = 10 ** system_float_precision()
	# round() first, as Frappe does before its own floor step, so 1.15 * 100 does not
	# become 114.999999999 and floor to 1.14.
	return math.floor(round(flt(value) * scale, 8)) / scale
