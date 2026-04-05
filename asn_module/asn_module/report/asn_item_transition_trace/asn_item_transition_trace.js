frappe.query_reports["ASN Item Transition Trace"] = {
	filters: [
		{
			fieldname: "asn",
			label: __("ASN"),
			fieldtype: "Link",
			options: "ASN",
			reqd: 0,
		},
		{
			fieldname: "item_code",
			label: __("Item Code"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "state",
			label: __("State"),
			fieldtype: "Data",
		},
		{
			fieldname: "transition_status",
			label: __("Status"),
			fieldtype: "Data",
		},
		{
			fieldname: "ref_doctype",
			label: __("Ref DocType"),
			fieldtype: "Link",
			options: "DocType",
		},
		{
			fieldname: "ref_name",
			label: __("Ref Name"),
			fieldtype: "Dynamic Link",
			get_options: () => frappe.query_report.get_filter_value("ref_doctype"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Datetime",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Datetime",
		},
		{
			fieldname: "failures_only",
			label: __("Failures only"),
			fieldtype: "Check",
		},
		{
			fieldname: "search",
			label: __("Search"),
			fieldtype: "Data",
		},
		{
			fieldname: "limit_page_length",
			label: __("Page limit"),
			fieldtype: "Int",
			default: 200,
		},
	],
};
