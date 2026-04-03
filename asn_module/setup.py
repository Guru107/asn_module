from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields


def after_install():
	setup_pr_fields()
	setup_pi_fields()
