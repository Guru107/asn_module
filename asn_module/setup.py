from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.custom_fields.supplier import setup as setup_supplier_fields
from asn_module.notifications.setup import create_notifications
from asn_module.setup_actions import register_actions


def after_install():
	setup_pr_fields()
	setup_pi_fields()
	setup_supplier_fields()
	create_notifications()
	register_actions()
