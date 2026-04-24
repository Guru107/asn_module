import frappe
from frappe import _
from frappe.model.document import Document

_NON_MAPPABLE_FIELDTYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"Button",
	"Fold",
	"Table",
	"Table MultiSelect",
	"HTML",
	"Heading",
	"Image",
}


class BarcodeMappingSet(Document):
	def autoname(self):
		mapping_set_name = (self.mapping_set_name or "").strip()
		if not mapping_set_name:
			frappe.throw(_("Mapping Set Name is required"))
		self.name = mapping_set_name

	def validate(self):
		self.mapping_set_name = (self.mapping_set_name or "").strip()
		if not self.mapping_set_name:
			frappe.throw(_("Mapping Set Name is required"))
		self.source_doctype = (self.source_doctype or "").strip()
		self.target_doctype = (self.target_doctype or "").strip()
		for row in list(self.rows or []):
			mapping_type = (row.mapping_type or "source").strip().lower()
			row.source_field = (row.source_field or "").strip()
			row.target_field = (row.target_field or "").strip()
			if mapping_type == "source" and not row.source_field:
				frappe.throw(_("Source Field is required for source mappings"))
			if not row.target_field:
				frappe.throw(_("Target Field is required"))

			if mapping_type == "source" and not _selector_from_docfield(
				row.source_field, self.source_doctype, "source"
			):
				frappe.throw(
					_("Source Field {0} is not valid for Source DocType {1}").format(
						row.source_field,
						self.source_doctype or _("(not set)"),
					)
				)

			if not _selector_from_docfield(row.target_field, self.target_doctype, "target"):
				frappe.throw(
					_("Target Field {0} is not valid for Target DocType {1}").format(
						row.target_field,
						self.target_doctype or _("(not set)"),
					)
				)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_mappable_docfields(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe._dict(filters or {})
	parent_doctype = (filters.get("parent_doctype") or "").strip()
	if not parent_doctype:
		return []

	rows = _mappable_docfields_rows(
		parent_doctype=parent_doctype,
		txt=txt,
		start=start,
		page_len=page_len,
	)
	return [[row[2], row[1]] for row in rows]


@frappe.whitelist()
def get_mappable_field_options(parent_doctype: str) -> list[str]:
	parent_doctype = (parent_doctype or "").strip()
	if not parent_doctype:
		return []

	rows = _mappable_docfields_rows(
		parent_doctype=parent_doctype,
		txt="",
		start=0,
		page_len=1000,
	)
	return [row[0] for row in rows]


def _mappable_docfields_rows(*, parent_doctype: str, txt: str, start: int, page_len: int):
	parents = [parent_doctype]
	items_doctype = _get_items_child_doctype(parent_doctype)
	if items_doctype:
		parents.append(items_doctype)

	search_text = (txt or "").strip()
	search_like = f"%{search_text}%"
	excluded = tuple(_NON_MAPPABLE_FIELDTYPES)
	return frappe.db.sql(
		"""
		SELECT
			CONCAT(df.parent, '.', df.fieldname) AS value,
			CONCAT(
				CASE
					WHEN df.parent = %(parent_doctype)s THEN 'Header'
					ELSE 'Items'
				END,
				' :: ',
				df.fieldname,
				CASE
					WHEN IFNULL(df.label, '') = '' THEN ''
					ELSE CONCAT(' — ', df.label)
				END
			) AS description,
			df.name AS docfield_name
		FROM `tabDocField` AS df
		WHERE
			df.parent IN %(parents)s
			AND IFNULL(df.hidden, 0) = 0
			AND IFNULL(df.fieldtype, '') NOT IN %(excluded)s
			AND (
				%(search_text)s = ''
				OR df.fieldname LIKE %(search_like)s
				OR IFNULL(df.label, '') LIKE %(search_like)s
			)
		ORDER BY
			CASE WHEN df.parent = %(parent_doctype)s THEN 0 ELSE 1 END,
			df.idx ASC
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"parent_doctype": parent_doctype,
			"parents": tuple(parents),
			"excluded": excluded,
			"search_text": search_text,
			"search_like": search_like,
			"start": int(start or 0),
			"page_len": int(page_len or 20),
		},
		as_list=True,
	)


def _selector_from_docfield(docfield_key: str, parent_doctype: str, side: str = "source") -> str:
	docfield_key = (docfield_key or "").strip()
	parent_doctype = (parent_doctype or "").strip()
	side = (side or "source").strip().lower()
	if not docfield_key or not parent_doctype:
		return ""
	if side not in {"source", "target"}:
		return ""

	field_parent, fieldname = _resolve_docfield_reference(docfield_key)
	if not field_parent or not fieldname:
		return ""

	if field_parent == parent_doctype:
		if side == "source":
			return f"header.{fieldname}"
		return fieldname

	items_doctype = _get_items_child_doctype(parent_doctype)
	if items_doctype and field_parent == items_doctype:
		return f"items[].{fieldname}"

	return ""


def _resolve_docfield_reference(reference: str) -> tuple[str, str]:
	reference = (reference or "").strip()
	if not reference:
		return "", ""
	if "." in reference:
		field_parent, fieldname = [part.strip() for part in reference.split(".", 1)]
		return field_parent, fieldname

	row = frappe.db.get_value("DocField", reference, ["parent", "fieldname"], as_dict=True)
	if not row:
		return "", ""
	return (row.get("parent") or "").strip(), (row.get("fieldname") or "").strip()


def _get_items_child_doctype(parent_doctype: str) -> str:
	parent_doctype = (parent_doctype or "").strip()
	if not parent_doctype:
		return ""

	meta = frappe.get_meta(parent_doctype)
	for field in list(meta.fields or []):
		fieldtype = (field.fieldtype or "").strip()
		if fieldtype not in {"Table", "Table MultiSelect"}:
			continue
		if (field.fieldname or "").strip() != "items":
			continue
		return (field.options or "").strip()
	return ""
