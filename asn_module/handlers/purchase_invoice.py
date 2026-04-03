import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as make_purchase_invoice_from_pr,
)
from frappe import _
from frappe.utils import flt


def create_from_purchase_receipt(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a draft Purchase Invoice from a submitted Purchase Receipt."""
	del source_doctype, payload

	pr = frappe.get_doc("Purchase Receipt", source_name)
	if pr.docstatus != 1:
		frappe.throw(
			_("Purchase Receipt {0} must be submitted before creating a Purchase Invoice").format(pr.name)
		)

	if flt(pr.per_billed) >= 100:
		frappe.throw(_("Purchase Receipt {0} is already fully billed").format(pr.name))

	existing_pi = frappe.db.get_value(
		"Purchase Invoice Item",
		{"purchase_receipt": pr.name, "docstatus": 0},
		"parent",
	)
	if existing_pi:
		return {
			"doctype": "Purchase Invoice",
			"name": existing_pi,
			"url": f"/app/purchase-invoice/{existing_pi}",
			"message": _("Existing draft Purchase Invoice {0} opened").format(existing_pi),
		}

	asn = frappe.get_doc("ASN", pr.asn) if pr.asn else None

	pi = make_purchase_invoice_from_pr(pr.name)
	pi.asn = pr.asn
	if asn:
		pi.bill_no = asn.supplier_invoice_no
		pi.bill_date = asn.supplier_invoice_date
	pi.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Invoice",
		"name": pi.name,
		"url": f"/app/purchase-invoice/{pi.name}",
		"message": _("Purchase Invoice {0} created from Purchase Receipt {1}").format(pi.name, pr.name),
	}
