from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from asn_module.notifications import setup as notifications_setup


class _FakeNotificationDoc:
	def __init__(self):
		self.values = {}
		self.recipients = []
		self.inserted = False
		self.saved = False

	def set(self, key, value):
		if key == "recipients":
			self.recipients = list(value)
			return
		self.values[key] = value

	def append(self, fieldname, row):
		if fieldname == "recipients":
			self.recipients.append(dict(row))

	def insert(self, ignore_permissions=False):
		self.inserted = True
		return self

	def save(self, ignore_permissions=False):
		self.saved = True
		return self


class TestNotificationSetup(FrappeTestCase):
	def test_create_notifications_is_idempotent_by_default(self):
		with patch("asn_module.notifications.setup.frappe.db.exists", return_value="ASN Submitted"):
			with patch("asn_module.notifications.setup.frappe.get_doc") as get_doc:
				notifications_setup.create_notifications()
				get_doc.assert_not_called()

	def test_create_notifications_reconciles_existing_when_enabled(self):
		existing = _FakeNotificationDoc()
		with patch("asn_module.notifications.setup.frappe.db.exists", return_value="ASN Submitted"):
			with patch("asn_module.notifications.setup.frappe.get_doc", return_value=existing):
				notifications_setup.create_notifications(update_existing=True)

		self.assertTrue(existing.saved)
		self.assertFalse(existing.inserted)
		self.assertGreater(len(existing.recipients), 0)

	def test_create_notifications_inserts_new_docs_with_recipients(self):
		new_doc = _FakeNotificationDoc()
		with patch("asn_module.notifications.setup.frappe.db.exists", return_value=False):
			with patch("asn_module.notifications.setup.frappe.get_doc", return_value=new_doc):
				notifications_setup.create_notifications()

		self.assertTrue(new_doc.inserted)
		self.assertFalse(new_doc.saved)
		self.assertGreater(len(new_doc.recipients), 0)

	def test_missing_recipient_configuration_throws_validation_error(self):
		template = {
			"name": "Template Missing Recipients",
			"document_type": "ASN",
			"event": "Submit",
			"channel": "Email",
		}
		with patch.object(
			notifications_setup,
			"NOTIFICATION_TEMPLATES",
			[*notifications_setup.NOTIFICATION_TEMPLATES, template],
		):
			with patch("asn_module.notifications.setup.frappe.db.exists", return_value=False):
				with patch(
					"asn_module.notifications.setup.frappe.get_doc", return_value=_FakeNotificationDoc()
				):
					with self.assertRaises(Exception):
						notifications_setup.create_notifications()
