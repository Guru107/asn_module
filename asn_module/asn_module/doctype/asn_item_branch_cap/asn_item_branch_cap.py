import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

NAME_SEPARATOR = "::"


class ASNItemBranchCap(Document):
	def validate(self):
		self._validate_non_negative_max_qty()
		self._validate_no_separator_in_keys()
		self._validate_no_duplicate_for_pair()
		self._warn_if_branch_has_no_cap_warehouses()

	def _validate_non_negative_max_qty(self):
		"""The sole non-negative check on ``max_qty``: the field no longer also carries the
		JSON ``non_negative`` flag. Frappe's own ``_validate_non_negative()`` runs inside
		``Document._validate()``, which ``run_before_save_methods()`` -- and therefore this
		``validate()`` -- always calls first, so for a field already checked here the JSON
		flag could never be the one to actually fire; it was dead weight duplicating this
		message with a generic one. This check wins by construction, so keeping it alone
		(and dropping the JSON flag) changes nothing observable, only removes the duplicate.
		"""
		if flt(self.max_qty) < 0:
			frappe.throw(_("Max Qty cannot be negative."))

	def _validate_no_separator_in_keys(self):
		"""The document name is {branch}::{item}, so the key enforces uniqueness.

		A branch or item containing the separator could collide two distinct pairs onto
		one record, which would silently overwrite a cap.
		"""
		for fieldname, label in (("branch", _("Branch")), ("item", _("Item"))):
			if NAME_SEPARATOR in (self.get(fieldname) or ""):
				frappe.throw(_("{0} must not contain {1}.").format(label, NAME_SEPARATOR))

	def _validate_no_duplicate_for_pair(self):
		"""The document name encodes (branch, item) at creation time, but a Branch or Item
		rename does not keep it that way. Both doctypes allow_rename, and Frappe's
		``rename_doc`` updates this row's ``branch``/``item`` Link values with
		``update_modified=False`` -- it never re-derives or renames this document to match.
		A rename therefore leaves a stale-named row whose columns already describe the new
		pair; the next cap entered for that pair gets a fresh, differently-named row with no
		duplicate-name error to stop it. ``_fetch_max_stock`` reads the ``branch``/``item``
		columns, not the name, so at that point two rows silently answer for one pair and
		whichever sorts last in ``modified desc`` order wins -- the name's own uniqueness
		guarantees nothing here.
		"""
		existing = frappe.db.get_value(
			"ASN Item Branch Cap", {"branch": self.branch, "item": self.item, "name": ["!=", self.name]}
		)
		if existing:
			frappe.throw(_("A cap already exists for {0} in {1}.").format(self.item, self.branch))

	def _warn_if_branch_has_no_cap_warehouses(self):
		"""Surface a cap that cannot take effect yet, at the moment someone sets it.

		The rule needs two things: this ceiling, and an enabled ASN Stock Cap Settings
		naming the warehouses whose stock counts. Without the second, this row is inert
		and nothing would otherwise say so. Deliberately a warning, not a block: the
		fail-open rule stands, and ceilings may legitimately be set before warehouses.

		Looked up by the ``branch`` field, not ``settings.name``. ``ASN Stock Cap
		Settings`` autonames from ``branch`` (``autoname: "field:branch"``) but has no
		rename handling, and Frappe's ``rename_doc`` only updates the Link *field value*
		on a renamed Branch's dependents -- it never renames or re-derives the dependent
		document itself (see ``stock_cap/fetch.py::_fetch_cap_warehouses`` for the same
		fix applied on the enforcement path). After a Branch rename this settings
		document's name is stale while its ``branch`` field already points at the new
		name, so matching on ``name`` would silently find nothing and this warning would
		stop firing for a branch that in fact has no cap warehouses configured. ``branch``
		carries a DB-level unique constraint, so this can never match more than one row.
		"""
		if not self.branch:
			return

		settings = frappe.db.get_value(
			"ASN Stock Cap Settings", {"branch": self.branch}, ["name", "enabled"], as_dict=True
		)
		if settings and settings.enabled:
			has_warehouse = frappe.db.exists(
				"ASN Stock Cap Warehouse", {"parent": settings.name, "parenttype": "ASN Stock Cap Settings"}
			)
			if has_warehouse:
				return

		frappe.msgprint(
			_(
				"Branch {0} has no enabled ASN Stock Cap Settings, so this limit will not be "
				"enforced until its cap warehouses are configured."
			).format(self.branch),
			title=_("Cap Not Yet Enforced"),
			indicator="orange",
		)


def on_doctype_update():
	"""Composite index backing ``_fetch_max_stock``, the hottest read in the cap check --
	it runs on every ASN and Purchase Receipt save and submit.

	Column order is (branch, item, max_qty), not (item, branch, max_qty), even though a
	DocField-level ``search_index`` already exists on ``item`` alone. The query filters
	both columns with an ``IN`` list
	(``filters={"branch": ["in", branches], "item": ["in", item_codes]}``), so either
	leading column satisfies the Leftmost Index Rule for range access. The tiebreaker is
	cardinality: ``branches`` is the set of distinct branches touched by the lines being
	evaluated, typically a handful even on a large multi-line ASN, while ``item_codes``
	is usually the longer list. Leading with the lower-cardinality column keeps the
	number of index range segments MariaDB has to probe (each ``branches`` value seeking
	to its own sub-range, then narrowing by ``item`` within it) close to
	``len(branches)``, not ``len(branches) * len(item_codes)``. This also matches the
	document's own natural key order -- ``autoname: "format:{branch}::{item}"`` already
	treats branch as the leading component of the pair.

	``max_qty`` is appended last purely to make the index covering: every column
	``_fetch_max_stock`` selects (``branch``, ``item``, ``max_qty``) is then satisfied
	from the index alone, with no bookmark lookup into the table.

	This is a plain, non-unique index. ``(branch, item)`` is logically unique -- enforced
	at validate time by ``_validate_no_duplicate_for_pair`` -- but a database-level unique
	constraint is a separate decision with its own migration risk (see the fix-c report)
	and is deliberately not made here.
	"""
	frappe.db.add_index("ASN Item Branch Cap", ["branch", "item", "max_qty"])
