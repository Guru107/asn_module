import frappe

# Recipient rows keyed by Notification name (Notification Recipient child table).
NOTIFICATION_RECIPIENTS = {
	"ASN Submitted": [{"receiver_by_role": "Stock Manager"}],
	"Purchase Receipt Ready for Billing": [{"receiver_by_role": "Accounts User"}],
}

# Retired templates (discrepancy never fired; the QC alert is stale since the QI flow was retired).
RETIRED_NOTIFICATIONS = ("ASN Discrepancy Detected", "QC Items Awaiting Inspection")

NOTIFICATION_TEMPLATES = [
	{
		"name": "ASN Submitted",
		"document_type": "ASN",
		"event": "Submit",
		"channel": "Email",
		"send_system_notification": 1,
		"subject": "New ASN {{ doc.name }} submitted by {{ doc.supplier }}",
		"message": (
			"A new ASN ({{ doc.name }}) has been submitted by {{ doc.supplier }}.\n\n"
			"Expected delivery: {{ doc.expected_delivery_date }}\n"
			"Invoice: {{ doc.supplier_invoice_no }}"
		),
	},
	{
		"name": "Purchase Receipt Ready for Billing",
		"document_type": "Purchase Receipt",
		"event": "Submit",
		"channel": "System Notification",
		"condition": "doc.asn",
		"subject": "Purchase Receipt {{ doc.name }} ready for billing",
		"message": (
			"Purchase Receipt {{ doc.name }} from {{ doc.supplier }} has been submitted "
			"and is ready for Purchase Invoice creation."
		),
	},
]


def _get_recipients(notification_name: str) -> list[dict]:
	recipients = NOTIFICATION_RECIPIENTS.get(notification_name)
	if not recipients:
		frappe.throw(f"Missing recipients config for notification '{notification_name}'")
	return recipients


def _apply_template(notif, template: dict) -> None:
	for fieldname, value in template.items():
		notif.set(fieldname, value)
	notif.set("enabled", 1)
	notif.set("recipients", [])

	for row in _get_recipients(template["name"]):
		notif.append("recipients", dict(row))


def create_notifications(update_existing: bool = False):
	"""Create Notification records for ASN events.

	Default behavior is idempotent creation by name. When update_existing=True,
	existing managed templates are reconciled to the latest module defaults.
	"""
	for retired in RETIRED_NOTIFICATIONS:
		if frappe.db.exists("Notification", retired):
			frappe.delete_doc("Notification", retired, ignore_permissions=True)

	for template in NOTIFICATION_TEMPLATES:
		name = template["name"]
		existing_name = frappe.db.exists("Notification", name)
		if existing_name and not update_existing:
			continue

		notif = (
			frappe.get_doc("Notification", existing_name)
			if existing_name
			else frappe.get_doc({"doctype": "Notification"})
		)
		_apply_template(notif, template)
		if existing_name:
			notif.save(ignore_permissions=True)
		else:
			notif.insert(ignore_permissions=True)
