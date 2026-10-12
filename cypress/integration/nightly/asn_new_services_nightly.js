context("ASN New Services nightly — validation error branches", () => {
	let seededData;

	function selectBulkTab() {
		cy.get("#bulk-tab").click();
		cy.location("hash", { timeout: 20000 }).should("eq", "#bulk");
	}

	function selectFirstInvoiceItem(poName) {
		cy.get("#single-po-input", { timeout: 20000 }).clear().type(poName);
		cy.get("#add-po-btn").click();
		cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
		cy.get("#single-item-picker-list input[type='checkbox']", { timeout: 20000 })
			.first()
			.check({ force: true });
	}

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
			(result) => {
				seededData = result;
			}
		);
	});

	beforeEach(() => {
		cy.login(seededData.portal_user, seededData.portal_password);
	});

	it("rejects duplicate PO SR No in same invoice group", () => {
		const po = seededData.purchase_orders[0];
		const invNo = "DUP-PO-SRN-" + Date.now();
		const csv = [
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
			`${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
			`${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
		].join("\n");
		cy.visit("/asn_new", { failOnStatusCode: false });
		selectBulkTab();
		cy.get("#asn-bulk-file-input").selectFile(
			{
				contents: Cypress.Buffer.from(csv),
				fileName: "dup_po_srno.csv",
				mimeType: "text/csv",
			},
			{ force: true }
		);
		cy.get("form#asn-bulk-upload-form button[type='submit']").click();
		cy.get("#bulk-pane .alert.alert-danger", { timeout: 15000 }).should("be.visible");
	});

	it("fills the supplier invoice amount from qty, rate, and tax", () => {
		const po = seededData.purchase_orders[0];
		cy.visit("/asn_new", { failOnStatusCode: false });
		selectFirstInvoiceItem(po.name);
		cy.get("form#single-asn-form input[name='supplier_invoice_no']")
			.clear()
			.type("MISMATCH-" + Date.now());
		cy.get("input[name='single_manual_qty']").first().clear().type("1");
		cy.get("input[name='single_manual_rate']").first().clear().type("100");
		cy.get("form#single-asn-form input[name='supplier_invoice_amount']").should(($input) => {
			const amount = Number($input.val());
			expect(amount).to.be.greaterThan(0);
		});
		cy.get("#single-manual-rows").then(($rows) => {
			cy.get("#supplier-invoice-amount").then(($amount) => {
				expect(
					$rows[0].compareDocumentPosition($amount[0]) & Node.DOCUMENT_POSITION_FOLLOWING
				).to.be.ok;
			});
		});
		cy.get("#supplier-invoice-amount").should("not.have.attr", "readonly");
	});
});
