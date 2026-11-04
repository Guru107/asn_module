def scan_code_field(insert_after: str | None) -> dict:
	"""The read-only Scan Code custom field shared by every chained document.

	Holds a copy of the code that creates the document's successor, filled by the
	submit hook. ``no_copy`` keeps a duplicate from inheriting another document's code.
	"""
	field = {
		"fieldname": "scan_code",
		"fieldtype": "Data",
		"label": "Scan Code",
		"read_only": 1,
		"no_copy": 1,
	}
	if insert_after:
		field["insert_after"] = insert_after
	return field
