# v16 ships IntegrationTestCase and keeps FrappeTestCase only as a deprecated shim (gone in v17);
# v15 has FrappeTestCase alone, with the same commit-on-setup and class-level rollback.
try:
	from frappe.tests import IntegrationTestCase
except ImportError:
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

__all__ = ["IntegrationTestCase"]
