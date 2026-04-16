context("ASN New portal nightly — single mode errors", () => {
	let seededData;

	function selectFirstInvoiceItem(poName) {
		cy.get("#single-po-input", { timeout: 20000 }).clear().type(poName);
		cy.get("#add-po-btn").click();
		cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
		cy.get("#single-item-picker-list input[type='checkbox']", { timeout: 20000 })
			.first()
			.check({ force: true });
	}

	function fillCommonSingleFields(invoiceNo) {
		cy.get("form#single-asn-form input[name='supplier_invoice_no']").clear().type(invoiceNo);
		cy.get("form#single-asn-form input[name='supplier_invoice_amount']").clear().type("100");
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

	it("rejects zero qty", () => {
		const po = seededData.purchase_orders[0];
		cy.visit("/asn_new", { failOnStatusCode: false });
		selectFirstInvoiceItem(po.name);
		fillCommonSingleFields("ZERO-QTY-" + Date.now());
		cy.get("input[name='single_manual_qty']").first().clear().type("0");
		cy.get("input[name='single_manual_rate']").first().clear().type("100");
		cy.get("form#single-asn-form button[type='submit']").click();
		cy.get("#single-pane .alert.alert-danger", { timeout: 15000 }).should("be.visible");
	});

	it("rejects negative rate", () => {
		const po = seededData.purchase_orders[0];
		cy.visit("/asn_new", { failOnStatusCode: false });
		selectFirstInvoiceItem(po.name);
		fillCommonSingleFields("NEG-RATE-" + Date.now());
		cy.get("input[name='single_manual_qty']").first().clear().type("1");
		cy.get("input[name='single_manual_rate']").first().clear().type("-1");
		cy.get("form#single-asn-form button[type='submit']").click();
		cy.get("input[name='single_manual_rate']")
			.first()
			.then(($input) => {
				expect($input[0].checkValidity()).to.equal(false);
			});
		cy.location("pathname").should("eq", "/asn_new");
	});
});

context("ASN New portal nightly — bulk mode errors", () => {
	let seededData;

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

	it("rejects CSV with missing required columns", () => {
		const badCsv = "supplier_invoice_no,supplier_invoice_amount\nINV-1,100";
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#bulk-tab").click();
		cy.location("hash", { timeout: 20000 }).should("eq", "#bulk");
		cy.get("#asn-bulk-file-input").selectFile(
			{
				contents: Cypress.Buffer.from(badCsv),
				fileName: "bad.csv",
				mimeType: "text/csv",
			},
			{ force: true }
		);
		cy.get("form#asn-bulk-upload-form button[type='submit']").click();
		cy.get("#bulk-pane .alert.alert-danger", { timeout: 15000 }).should("be.visible");
	});

	it("rejects qty greater than remaining on PO in CSV", () => {
		const po = seededData.purchase_orders[0];
		const csv = [
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
			`OVERQTY-${Date.now()},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,99999,${
				po.name
			},1,${po.items[0].item_code},99999,100`,
		].join("\n");
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#bulk-tab").click();
		cy.location("hash", { timeout: 20000 }).should("eq", "#bulk");
		cy.get("#asn-bulk-file-input").selectFile(
			{
				contents: Cypress.Buffer.from(csv),
				fileName: "overqty.csv",
				mimeType: "text/csv",
			},
			{ force: true }
		);
		cy.get("form#asn-bulk-upload-form button[type='submit']").click();
		cy.get("#bulk-pane .alert.alert-danger", { timeout: 15000 }).should("be.visible");
	});
});
