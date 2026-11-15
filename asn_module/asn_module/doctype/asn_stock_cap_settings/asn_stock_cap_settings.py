import frappe
from frappe import _
from frappe.model.document import Document


class ASNStockCapSettings(Document):
	def validate(self):
		self._validate_leaf_warehouses()
		self._validate_no_duplicates()
		self._validate_not_claimed_by_another_branch()

	def _validate_leaf_warehouses(self):
		warehouses = [row.warehouse for row in self.warehouses or []]
		if not warehouses:
			return

		groups = set(
			frappe.get_all("Warehouse", filters={"name": ["in", warehouses], "is_group": 1}, pluck="name")
		)
		for row in self.warehouses:
			if row.warehouse not in groups:
				continue

			frappe.throw(
				_(
					"Row {0}: {1} is a group warehouse. Stock is only recorded against leaf "
					"warehouses, so a group would never count toward the cap. List its leaves instead."
				).format(row.idx, row.warehouse)
			)

	def _validate_no_duplicates(self):
		seen = set()
		for row in self.warehouses or []:
			if row.warehouse not in seen:
				seen.add(row.warehouse)
				continue

			frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, row.warehouse))

	def _validate_not_claimed_by_another_branch(self):
		warehouses = [row.warehouse for row in self.warehouses or []]
		if not warehouses:
			return

		filters = {"warehouse": ["in", warehouses], "parenttype": "ASN Stock Cap Settings"}
		if self.name:
			filters["parent"] = ["!=", self.name]

		claimed = frappe.get_all(
			"ASN Stock Cap Warehouse", filters=filters, fields=["parent", "warehouse"], limit=1
		)
		if not claimed:
			return

		# The settings document is named after its branch, but the name is not the live branch value.
		branch = frappe.db.get_value("ASN Stock Cap Settings", claimed[0].parent, "branch")
		frappe.throw(
			_(
				"Warehouse {0} is already a cap warehouse for branch {1}. "
				"A warehouse can belong to only one branch."
			).format(claimed[0].warehouse, branch or claimed[0].parent)
		)
