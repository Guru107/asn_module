from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.notifications.setup import create_notifications


def after_install():
	setup_pr_fields()
	setup_pi_fields()
	create_notifications()
