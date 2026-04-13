context("ASN New portal nightly — 100 item PO flows", () => {
	let seededData;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_large_po_context").then(
			(result) => {
				seededData = result;
			}
		);
	});

	beforeEach(() => {
		cy.login(seededData.portal_user, seededData.portal_password);
	});

	it("submits single ASN from a 100-line purchase order", () => {
		const poName = seededData.purchase_order.name;
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#single-po-input", { timeout: 20000 }).clear().type(poName);
		cy.get("#add-po-btn").click();
		cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
		cy.get("#single-item-picker-list input[type='checkbox']", { timeout: 20000 }).should(
			"have.length",
			100
		);

		cy.get("#single-item-picker-list input[type='checkbox']").first().check({ force: true });
		cy.get("#single-item-picker-list input[type='checkbox']").eq(99).check({ force: true });
		cy.get("#single-manual-rows .single-row", { timeout: 20000 }).should("have.length", 2);

		cy.get("form#single-asn-form input[name='supplier_invoice_no']")
			.clear()
			.type("SINGLE-100-" + Date.now());
		cy.get("form#single-asn-form input[name='supplier_invoice_amount']").clear().type("20");
		cy.get("input[name='single_manual_qty']").each(($input) => {
			cy.wrap($input).clear().type("1");
		});
		cy.get("input[name='single_manual_rate']").each(($input) => {
			cy.wrap($input).clear().type("10");
		});
		cy.get("form#single-asn-form button[type='submit']").click();
		cy.location("pathname", { timeout: 20000 }).should("match", /\/asn\/asn-[^/]+$/i);
	});

	it("submits bulk ASN from a 100-line purchase order CSV", () => {
		const po = seededData.purchase_order;
		const invoiceNo = "BULK-100-" + Date.now();
		const csvLines = [
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
		];
		for (let idx = 1; idx <= 100; idx++) {
			csvLines.push(
				`${invoiceNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,1000,${po.name},${idx},${po.items[0].item_code},1,10`
			);
		}
		const csv = csvLines.join("\n");

		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#bulk-tab").click();
		cy.location("hash", { timeout: 20000 }).should("eq", "#bulk");
		cy.get("#asn-bulk-file-input").selectFile(
			{
				contents: Cypress.Buffer.from(csv),
				fileName: "bulk_100_items.csv",
				mimeType: "text/csv",
			},
			{ force: true }
		);
		cy.get("form#asn-bulk-upload-form button[type='submit']").click();
		cy.get("#bulk-pane .alert.alert-success", { timeout: 20000 })
			.should("be.visible")
			.and("contain.text", "Created and submitted 1 ASN");
	});
});
