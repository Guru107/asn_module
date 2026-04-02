import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today
from frappe.utils.file_manager import save_file

from asn_module.qr_engine.generate import generate_barcode, generate_qr


class ASN(Document):
	def validate(self):
		self._validate_items_present()
		self._validate_item_qty()
		self._validate_supplier_invoice_unique()
		self._validate_po_qty()

	def on_submit(self):
		self.status = "Submitted"
		self.asn_date = today()
		self._generate_attachments()
		frappe.db.set_value(
			self.doctype,
			self.name,
			{
				"status": self.status,
				"asn_date": self.asn_date,
				"qr_code": self.qr_code,
				"barcode": self.barcode,
			},
			update_modified=False,
		)

	def on_cancel(self):
		self.status = "Cancelled"
		frappe.db.set_value(self.doctype, self.name, "status", self.status, update_modified=False)

	def _validate_items_present(self):
		if self.items:
			return

		frappe.throw(_("At least one item is required in the ASN"))

	def _validate_item_qty(self):
		for row in self.items or []:
			if flt(row.qty) > 0:
				continue

			frappe.throw(_("Row {0}: Quantity must be greater than 0").format(row.idx))

	def _validate_supplier_invoice_unique(self):
		if not self.supplier_invoice_no:
			return

		filters = [
			"supplier = %s",
			"supplier_invoice_no = %s",
			"docstatus != 2",
		]
		params = [self.supplier, self.supplier_invoice_no]

		if self.name:
			filters.append("name != %s")
			params.append(self.name)

		existing = frappe.db.sql(
			f"""
			SELECT name
			FROM `tabASN`
			WHERE {" AND ".join(filters)}
			LIMIT 1
			""",
			params,
		)
		if existing:
			frappe.throw(
				_("Supplier Invoice No {0} already exists for Supplier {1}").format(
					self.supplier_invoice_no, self.supplier
				)
			)

	def _validate_po_qty(self):
		rows_by_purchase_order_item = {}
		for row in self.items or []:
			if not row.purchase_order or not row.purchase_order_item:
				continue

			rows_by_purchase_order_item.setdefault(row.purchase_order_item, []).append(row)

		if not rows_by_purchase_order_item:
			return

		purchase_order_item_names = list(rows_by_purchase_order_item)
		po_items = frappe.get_all(
			"Purchase Order Item",
			filters={"name": ["in", purchase_order_item_names]},
			fields=["name", "qty"],
		)
		po_qty_by_item = {row.name: flt(row.qty) for row in po_items}

		params = purchase_order_item_names.copy()
		name_clause = ""
		if self.name:
			name_clause = "AND a.name != %s"
			params.append(self.name)

		placeholders = ", ".join(["%s"] * len(purchase_order_item_names))
		existing_rows = frappe.db.sql(
			f"""
			SELECT ai.purchase_order_item, COALESCE(SUM(ai.qty), 0) AS qty
			FROM `tabASN Item` ai
			INNER JOIN `tabASN` a ON a.name = ai.parent
			WHERE ai.purchase_order_item IN ({placeholders})
			AND a.docstatus != 2
			{name_clause}
			GROUP BY ai.purchase_order_item
			""",
			params,
			as_dict=True,
		)
		existing_qty_by_item = {row.purchase_order_item: flt(row.qty) for row in existing_rows}

		for purchase_order_item, rows in rows_by_purchase_order_item.items():
			po_qty = po_qty_by_item.get(purchase_order_item)
			if not po_qty:
				continue

			current_qty = sum(flt(row.qty) for row in rows)
			already_shipped = existing_qty_by_item.get(purchase_order_item, 0)
			remaining_qty = flt(po_qty) - flt(already_shipped)
			if flt(current_qty) <= flt(remaining_qty):
				continue

			row_numbers = ", ".join(str(row.idx) for row in rows)
			frappe.throw(
				_("Rows {0}: Shipped qty {1} exceeds remaining PO qty {2}").format(
					row_numbers,
					current_qty,
					remaining_qty,
				)
			)

	def _generate_attachments(self):
		qr_result = generate_qr("create_purchase_receipt", "ASN", self.name)
		barcode_result = generate_barcode("create_purchase_receipt", "ASN", self.name)

		qr_file = save_file(
			f"{self.name}-qr.png",
			qr_result["image_base64"],
			self.doctype,
			self.name,
			is_private=0,
			decode=True,
		)
		barcode_file = save_file(
			f"{self.name}-barcode.png",
			barcode_result["image_base64"],
			self.doctype,
			self.name,
			is_private=0,
			decode=True,
		)

		self.qr_code = qr_file.file_url
		self.barcode = barcode_file.file_url


@frappe.whitelist()
def get_purchase_order_items(purchase_order: str, asn_name: str | None = None) -> list[dict]:
	po_items = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=[
			"name as purchase_order_item",
			"item_code",
			"item_name",
			"qty",
			"uom",
			"rate",
		],
	)

	result = []
	for poi in po_items:
		already_shipped = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(ai.qty), 0)
			FROM `tabASN Item` ai
			INNER JOIN `tabASN` a ON a.name = ai.parent
			WHERE ai.purchase_order_item = %s
			AND a.name != %s
			AND a.docstatus != 2
			""",
			(poi.purchase_order_item, asn_name or ""),
		)[0][0]

		remaining_qty = flt(poi.qty) - flt(already_shipped)
		if remaining_qty <= 0:
			continue

		result.append(
			{
				"purchase_order": purchase_order,
				"purchase_order_item": poi.purchase_order_item,
				"item_code": poi.item_code,
				"item_name": poi.item_name,
				"qty": remaining_qty,
				"uom": poi.uom,
				"rate": poi.rate,
			}
		)

	return result


@frappe.whitelist()
def get_po_items(doctype, txt, searchfield, start, page_len, filters):
	purchase_order = (filters or {}).get("purchase_order")
	if not purchase_order:
		return []

	return frappe.db.sql(
		"""
		SELECT poi.item_code, poi.item_name
		FROM `tabPurchase Order Item` poi
		WHERE poi.parent = %s
		AND (poi.item_code LIKE %s OR poi.item_name LIKE %s)
		LIMIT %s OFFSET %s
		""",
		(purchase_order, f"%{txt}%", f"%{txt}%", page_len, start),
	)
