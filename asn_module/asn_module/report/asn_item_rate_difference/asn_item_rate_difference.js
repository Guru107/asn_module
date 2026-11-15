frappe.query_reports["ASN Item Rate Difference"] = {
	filters: [
		{
			fieldname: "asn",
			label: __("ASN"),
			fieldtype: "Link",
			options: "ASN",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "purchase_order",
			label: __("Purchase Order"),
			fieldtype: "Link",
			options: "Purchase Order",
		},
		{
			fieldname: "supplier_invoice_no",
			label: __("Supplier Invoice No"),
			fieldtype: "Data",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],
};
