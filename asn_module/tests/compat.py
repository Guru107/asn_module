try:
    from frappe.tests import UnitTestCase
except ImportError:  # Frappe v15 fallback
    from frappe.tests.utils import FrappeTestCase as UnitTestCase

__all__ = ["UnitTestCase"]
