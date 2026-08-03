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
		"""
		if not self.branch:
			return

		settings = frappe.db.get_value(
			"ASN Stock Cap Settings", self.branch, ["name", "enabled"], as_dict=True
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
