import frappe


def register_actions():
	"""Register all QR actions in the QR Action Registry."""
	actions = [
		{
			"action_key": "create_purchase_receipt",
			"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
			"source_doctype": "ASN",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_stock_transfer",
			"handler_method": "asn_module.handlers.stock_transfer.create_from_quality_inspection",
			"source_doctype": "Quality Inspection",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_purchase_return",
			"handler_method": "asn_module.handlers.purchase_return.create_from_quality_inspection",
			"source_doctype": "Quality Inspection",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_purchase_invoice",
			"handler_method": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
			"source_doctype": "Purchase Receipt",
			"roles": ["Accounts User", "Accounts Manager"],
		},
		{
			"action_key": "confirm_putaway",
			"handler_method": "asn_module.handlers.putaway.confirm_putaway",
			"source_doctype": "Purchase Receipt",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_subcontracting_dispatch",
			"handler_method": "asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order",
			"source_doctype": "Subcontracting Order",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_subcontracting_receipt",
			"handler_method": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
			"source_doctype": "Subcontracting Order",
			"roles": ["Stock User", "Stock Manager"],
		},
	]

	registry = frappe.get_single("QR Action Registry")
	# Reset to the module's managed defaults for deterministic fresh installs.
	registry.actions = []

	for row in actions:
		registry.append(
			"actions",
			{
				"action_key": row["action_key"],
				"handler_method": row["handler_method"],
				"source_doctype": row["source_doctype"],
				"allowed_roles": ",".join(row["roles"]),
			},
		)

	registry.save(ignore_permissions=True)
