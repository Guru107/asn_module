"""Code-defined QR actions. This map is the only registry."""

ACTIONS = {
	"create_purchase_receipt": {
		"handler": "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
		"source_doctype": "ASN",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_gate_pass_from_asn": {
		"handler": "asn_module.handlers.purchase_receipt.create_gate_pass_from_asn",
		"source_doctype": "ASN",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_receipt_from_gate_pass": {
		"handler": "asn_module.handlers.purchase_receipt.create_receipt_from_gate_pass_scan",
		"source_doctype": "Gate Pass",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_purchase_invoice": {
		"handler": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
		"source_doctype": "Purchase Receipt",
		"roles": ["Accounts User", "Accounts Manager"],
	},
	"create_subcontracting_dispatch": {
		"handler": "asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order",
		"source_doctype": "Subcontracting Order",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_subcontracting_receipt": {
		"handler": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
		"source_doctype": "Subcontracting Order",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_subcontracting_receipt_from_dispatch": {
		"handler": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_dispatch",
		"source_doctype": "Stock Entry",
		"roles": ["Stock User", "Stock Manager"],
	},
	"create_purchase_receipt_from_subcontracting_receipt": {
		"handler": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_receipt",
		"source_doctype": "Subcontracting Receipt",
		"roles": ["Stock User", "Stock Manager"],
	},
}


def get_action(action_key: str) -> dict | None:
	"""Return handler, source doctype, and roles for one action key."""
	row = ACTIONS.get((action_key or "").strip())
	if not row:
		return None
	return {
		"handler": row["handler"],
		"source_doctype": row["source_doctype"],
		"allowed_roles": list(row["roles"]),
	}
