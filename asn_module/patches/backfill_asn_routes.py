import frappe
from frappe.query_builder.functions import IfNull


def execute():
	"""Store the ``asn/<name>`` portal route on ASNs that still have none or a bare slug.

	The supplier portal used to repair the route with a write inside ``get_context``;
	``ASN.make_route`` now sets it on save, so only older rows need this. Rows that already
	start with ``asn/`` are skipped, which keeps a repeat run a no-op.
	"""
	asn = frappe.qb.DocType("ASN")
	names = (frappe.qb.from_(asn).select(asn.name).where(IfNull(asn.route, "").not_like("asn/%"))).run(
		pluck="name"
	)
	for name in names:
		route = frappe.get_doc("ASN", name).make_route()
		frappe.qb.update(asn).set(asn.route, route).where(asn.name == name).run()
